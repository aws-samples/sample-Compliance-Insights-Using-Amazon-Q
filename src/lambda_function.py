import boto3
from botocore.exceptions import ClientError
from datetime import datetime, timedelta
import gzip
import re
import json
import os
import logging
import jmespath


logger = logging.getLogger()
logger.setLevel(logging.INFO)

def parse_s3_arn(arn):
    """
    Parse S3 ARN to extract bucket name and optional path
    """
    parts = arn.split(':', 5)
    if len(parts) < 6:
        raise ValueError(f"Invalid S3 ARN format: {arn}")

    s3_parts = parts[5].split('/', 1)
    bucket_name = s3_parts[0]
    prefix = s3_parts[1] if len(s3_parts) > 1 else ''

    return bucket_name, prefix

def assume_source_role():
    """
    Assume the role in the source account for S3 access
    """
    try:
        sts_client = boto3.client('sts')
        source_account_id = os.environ['SOURCE_ACCOUNT_ID']
        role_arn = f"arn:aws:iam::{source_account_id}:role/ConfigDataReadRole"
        logger.info(f"Attempting to assume role: {role_arn}")

        response = sts_client.assume_role(
            RoleArn=role_arn,
            RoleSessionName="S3CopySession"
        )

        credentials = response['Credentials']

        session = boto3.Session(
            aws_access_key_id=credentials['AccessKeyId'],
            aws_secret_access_key=credentials['SecretAccessKey'],
            aws_session_token=credentials['SessionToken']
        )

        logger.info(f"Successfully assumed role in account {source_account_id}")
        return session

    except ClientError as e:
        logger.error(f"Error assuming role: {str(e)}")
        raise

def check_bucket_access(s3_client, bucket):
    """
    Check if a bucket exists and is accessible
    """
    try:
        s3_client.head_bucket(Bucket=bucket)
    except ClientError as e:
        error_code = e.response['Error']['Code']
        if error_code == '403':
            logger.error(f"Access denied to bucket {bucket}")
            raise
        elif error_code == '404':
            logger.error(f"Bucket {bucket} does not exist")
            raise
        else:
            logger.error(f"Error accessing bucket {bucket}: {str(e)}")
            raise

def get_org_prefix_for_config(s3_client, bucket):
    """
    Identify the org prefix for Config logs by checking common Control Tower patterns
    """
    try:
        common_prefixes = [
            "o-",  # Organization prefix
            "AWSLogs/"  # Direct AWSLogs prefix
        ]

        paginator = s3_client.get_paginator('list_objects_v2')

        # Try to find organization ID prefix first
        for prefix in common_prefixes:
            try:
                response = s3_client.list_objects_v2(
                    Bucket=bucket,
                    Prefix=prefix,
                    MaxKeys=1
                )
                if 'Contents' in response:
                    # If we found an org prefix, get the full org path
                    if prefix == "o-":
                        # Get the first object key
                        first_key = response['Contents'][0]['Key']
                        # Extract org path up to AWSLogs
                        org_path = first_key.split('AWSLogs')[0]
                        logger.info(f"Found organization path: {org_path}")
                        return org_path + "AWSLogs"
                    else:
                        logger.info(f"Found org prefix: {prefix}")
                        return prefix
            except ClientError as e:
                logger.warning(f"Error checking prefix {prefix}: {str(e)}")
                continue

        # If no prefix found, return empty string
        logger.info("No specific org prefix found, will list from bucket root")
        return ""

    except Exception as e:
        logger.error(f"Error in get_org_prefix_for_config: {str(e)}")
        return ""

def get_date_based_objects(s3_client, bucket, current_date, account_list=None, region_list=None):
    """
    Get objects matching the Config pattern for a specific date with account and region filtering
    """
    try:

        matching_objects = []

        # Get the org prefix for more efficient listing
        org_prefix = get_org_prefix_for_config(s3_client, bucket)
        logger.info(f"Using org prefix: {org_prefix}")

        # Format the date components with zero-padding for single digits
        date_pattern = (f"{current_date.year}/"
                       f"{current_date.month}/"
                       f"{current_date.day}")

        # If no account list provided, log warning and return empty
        if not account_list:
            logger.warning("No account list provided")
            return []

        # Iterate through each account
        for account_id in account_list:
            # Construct specific base prefix for this account
            base_prefix = f"{org_prefix}/{account_id}/Config"
            logger.info(f"Processing account {account_id} with base prefix: {base_prefix}")

            # Build region condition if regions specified
            region_condition = ""
            if region_list:
                region_patterns = [f"contains(Key, '/Config/{reg}/')" for reg in region_list]
                region_condition = f" && ({' || '.join(region_patterns)})"

            # JMESPath expression for this account
            jmespath_expression = f"""
            Contents[?
                contains(Key, '{date_pattern}/') &&
                !contains(Key, 'ConfigWritabilityCheckFile'){region_condition}
            ]
            """

            logger.info(f"Using JMESPath expression for account {account_id}: {jmespath_expression}")

            # Use list_objects_v2 with pagination for this account
            paginator = s3_client.get_paginator('list_objects_v2')
            page_iterator = paginator.paginate(
                Bucket=bucket,
                Prefix=base_prefix,
                PaginationConfig={
                    'MaxItems': 10000,
                    'PageSize': 1000
                }
            )

            # Process each page for this account
            account_objects = []
            for page_number, page in enumerate(page_iterator, 1):
                logger.info(f"Processing page {page_number} for account {account_id}")

                if 'Contents' in page:
                    filtered_contents = jmespath.search(jmespath_expression, page)
                    if filtered_contents:
                        account_objects.extend(filtered_contents)
                        logger.info(f"Found {len(filtered_contents)} matching objects on page {page_number} for account {account_id}")

                        # Log sample keys for verification
                        sample_keys = [obj['Key'] for obj in filtered_contents[:2]]
                        logger.info(f"Sample keys from account {account_id}: {sample_keys}")

            logger.info(f"Total objects found for account {account_id}: {len(account_objects)}")
            matching_objects.extend(account_objects)

        # Log total objects found across all accounts
        logger.info(f"Total matching objects found across all accounts: {len(matching_objects)}")

        # Verify account coverage
        found_accounts = set()
        for obj in matching_objects:
            for acc in account_list:
                if f"/AWSLogs/{acc}/" in obj['Key']:
                    found_accounts.add(acc)

        logger.info(f"Found objects for accounts: {found_accounts}")
        missing_accounts = set(account_list) - found_accounts
        if missing_accounts:
            logger.warning(f"Missing objects for accounts: {missing_accounts}")

        return matching_objects

    except Exception as e:
        logger.error(f"Error in get_date_based_objects: {str(e)}")
        raise

def lambda_handler(event, context):
    """
    AWS Lambda handler to copy Config data between S3 buckets
    """
    try:
        # Get parameters from environment variables
        source_bucket_arn = os.environ['SOURCE_BUCKET_ARN']
        destination_bucket = os.environ['DESTINATION_BUCKET']

        # Parse account and region lists
        account_list_str = os.environ.get('ACCOUNT_LIST', '')
        region_list_str = os.environ.get('REGION_LIST', '')

        # Parse account list
        account_list = [acc.strip() for acc in account_list_str.split(',') if acc.strip()]
        # Parse region list
        region_list = [reg.strip() for reg in region_list_str.split(',') if reg.strip()]

        # Parse source bucket from ARN
        source_bucket, source_prefix = parse_s3_arn(source_bucket_arn)

        # Parse source account Id from ARN
        source_account_id = os.environ['SOURCE_ACCOUNT_ID']

        logger.info(f"Source bucket ARN: {source_bucket_arn}")

        # Assume role in source account
        source_session = assume_source_role() # Assume role in source account
        source_s3_client = source_session.client('s3')


        # Create destination S3 client in current account
        s3_client = boto3.client('s3')

        # Calculate the date based on cutoff date
        cutoff_date = datetime.now() - timedelta(days=7)
        current_date = datetime.now()

        # Log configuration
        logger.info("\nConfiguration:")
        logger.info(f"Source bucket: {source_bucket}")
        logger.info(f"Destination bucket: {destination_bucket}")
        if account_list:
            logger.info(f"Account list: {account_list}")
        if region_list:
            logger.info(f"Region list: {region_list}")

        # Counters for statistics
        copied_files = 0
        skipped_existing = 0

        # Check if buckets exist and are accessible
        check_bucket_access(source_s3_client, source_bucket)
        check_bucket_access(s3_client, destination_bucket)

        try:

            while current_date >= cutoff_date:

                logger.info(f"Processing date: {current_date.strftime('%Y/%m/%d')}")

                # Initialize paginator for handling large buckets
                #paginator = source_s3_client.get_paginator('list_objects_v2')

                # Get matching objects for current date
                matching_objects = get_date_based_objects(
                    s3_client=source_s3_client,
                    bucket=source_bucket,
                    current_date=current_date,
                    account_list=account_list,
                    region_list=region_list
                )

                for obj in matching_objects:
                    source_key = obj['Key']
                    logger.info(f"Processing object: {source_key}")

                    # Convert LastModified to the same timezone as cutoff_date (local time)
                    last_modified = obj['LastModified'].replace(tzinfo=None)
                    source_key = obj['Key']
                    destination_key = source_key

                     # Remove .gz extension from destination key if source is compressed
                    if source_key.endswith('.gz'):
                        destination_key = destination_key[:-3]

                        # Check if file already exists in destination
                        try:
                            s3_client.head_object(Bucket=destination_bucket, Key=destination_key)
                            status = "Skipped (already exists)"
                            skipped_existing += 1
                            #logger.info(f"{last_modified.strftime('%Y-%m-%d %H:%M:%S'):<25} "
                            #    f"{source_key:<65} {status}")
                            continue
                        except s3_client.exceptions.ClientError as e:
                            if e.response['Error']['Code'] != '404':
                                raise e

                        try:
                            # Handle .gz files
                            if source_key.endswith('.gz'):
                                response = source_s3_client.get_object(Bucket=source_bucket, Key=source_key)
                                compressed_content = response['Body'].read()
                                decompressed_content = gzip.decompress(compressed_content)

                                s3_client.put_object(
                                    Bucket=destination_bucket,
                                    Key=destination_key,
                                    Body=decompressed_content,
                                    ContentType='application/json'
                                )
                            else:
                                copy_source = {
                                    'Bucket': source_bucket,
                                    'Key': source_key
                                }
                                s3_client.copy_object(
                                    CopySource=copy_source,
                                    Bucket=destination_bucket,
                                    Key=destination_key
                                )

                            copied_files += 1
                            status = "Copied successfully"
                            logger.info(f"{last_modified.strftime('%Y-%m-%d %H:%M:%S'):<25} "
                                        f"{source_key:<65} {status}")
                        except ClientError as e:
                            error_code = e.response['Error']['Code']
                            if error_code == 'NoSuchKey':
                                logger.error(f"Source object {source_key} does not exist")
                                raise
                            else:
                                logger.error(f"Error copying object: {str(e)}")
                                raise

                # At the end of the loop, decrement the date
                current_date = current_date - timedelta(days=1)

            logger.info("-" * 120)
            logger.info(f"\nFiles copied: {copied_files}")
            logger.info(f"Files skipped (already exist): {skipped_existing}")

            return {
                'statusCode': 200,
                'body': json.dumps({
                    'message': 'Config data copy completed successfully',
                    'files_copied': copied_files,
                    'files_skipped': skipped_existing,
                    'configuration': {
                        'source_bucket': source_bucket,
                        'destination_bucket': destination_bucket,
                        'account_list': account_list,
                        'region_list': region_list
                    }
                })
            }
        except Exception as e:
            logger.error(f"Error occurred: {str(e)}")
            return {
                'statusCode': 500,
                'body': json.dumps({
                    'error': str(e)
                })
            }
    finally:
        logger.info("Lambda function execution completed.")
