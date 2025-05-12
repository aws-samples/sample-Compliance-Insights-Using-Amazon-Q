# Gain Compliance Insights in your AWS Environment Using Amazon Q Business

Enterprise organizations managing multiple AWS accounts face complexity
as their cloud infrastructure scales. The exponential growth in
resources, coupled with diverse configuration requirements across
different business units, creates significant challenges in maintaining
effective oversight of AWS environments.\
\
[AWS Config](https://aws.amazon.com/config/) is a service that
continually assesses, audits, and evaluates the configurations and
relationships of your resources on AWS, on premises, and on other
clouds. The AWS Config data is stored in secure Amazon S3 buckets.\
When combined with the natural language processing capabilities of
Amazon Q Business, this AWS Config data can be transformed into a
powerful source of actionable intelligence.\
\
In this blog post, we will show how security and compliance teams can
now use AWS Config and Amazon Q Business to gain deep visibility into
their AWS ecosystem. By leveraging natural language queries, teams can
effortlessly access critical compliance insights, proactively identify
potential risks, streamline auditing processes and and make data-driven
decisions to enhance their security framework.

------------------------------------------------------------------------

## Overview of the Solution

Our solution addresses this challenge by integrating AWS Config, Amazon
S3, and Amazon Q Business to create a natural language-powered interface
for querying AWS resource configurations. Here\'s how it works:

1.  **Extract relevant AWS Config Data** : Our solution periodically
    extracts the AWS Config data from the central Amazon S3 Bucket for
    the AWS Config to a secure S3 bucket in an audit account for a list
    selected AWS Accounts and regions.

2.  **Process the Data with Amazon Q Business**: Amazon Q Business is a
    powerful NLP service that can understand and respond to natural
    language queries. In this solution, we\'ll configure Q Business to
    parse the AWS Config data stored in the secure S3 bucket in your
    audit account and create a knowledge base that can be queried using
    natural language.

3.  **Query the Knowledge Base with Natural Language**: With the
    knowledge base created by Q Business, users can now ask natural
    language questions about their AWS environment, such as \"Which EC2
    instances are running in my us-west-2 account?\" or \"What is the
    configuration of my RDS database in my development environment?\". Q
    Business will then provide the relevant information from the
    underlying AWS Config data.

By implementing this solution, your team members can easily access and
understand the configuration of their AWS resources without requiring
deep AWS expertise. This can help streamline decision-making, improve
compliance monitoring, and enhance overall visibility into your cloud
infrastructure.

## The Solution Architecture

![](images/SolutionArchitecture.png){width="6.5in" height="5.804861111111111in"}

## Prerequisites

In AWS Control tower managed organizations, the audit account and log
archive account are shared accounts that is set up automatically when
you create your landing zone. The log archive account contains a central
Amazon S3 bucket for storing a copy of all AWS CloudTrail and AWS Config
log files for all other accounts in your landing zone. 

The audit account should be restricted to security and compliance teams
with auditor (read-only) and administrator (full-access) cross-account
roles to all accounts in the landing zone. These roles are intended to
be used by security and compliance teams to perform audits through AWS
mechanisms

This solution is designed to be deployed in the audit account which can
provide an isolated environment to host the required AWS Config data
required for Amazon Q Business.

If you are deploying, this solution in AWS Organizations not managed by
AWS Control tower, we still recommend you deploy it in an audit account
which is separate from the central log account.

Before we dive into the solution, let's look at the prerequisites that
are required to get started:

1.  An AWS account with access to the AWS Management Console of an Audit
    account where this solution will be deployed.

2.  [AWS
    CLI](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html)
    to deploy the necessary artifacts using [AWS
    CloudFormation](https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/Welcome.html)

3.  [SAM
    CLI](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/serverless-sam-cli-install.html)
    -- Install the SAM CLI. The Serverless Application Model Command
    Line Interface (SAM CLI) is an extension of the AWS CLI that adds
    functionality for building and testing Lambda applications.

## How to build and Deploy the Solution

### Step 1: Deploy a ConfigDataReadRole IAM role in the log account which hosts the Central S3 bucket for AWS Config.

Using AWS CLI on the log account, create the ConfigDataReadRole role
with the trust policy. Ensure to replace the Principal to AWS account id of your audit account.

```bash

cat << 'EOF' > trust-policy.json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Principal": {
                "AWS": "arn:aws:iam::1234567890:root"
            },
            "Action": "sts:AssumeRole",
            "Condition": {}
        }
    ]
}
EOF
```
```bash
aws iam create-role \
    --role-name ConfigDataReadRole \
    --assume-role-policy-document file://trust-policy.json

aws iam attach-role-policy \
    --role-name ConfigDataReadRole \
    --policy-arn arn:aws:iam::aws:policy/AmazonS3ReadOnlyAccess


```

### Step 2: Deploy the solution in the audit account

Using AWS CLI on the audit account, deploy the solution.

```bash
git clone git@ssh.gitlab.aws.dev:cca-ambassadors/compliance-insights-using-amazon-q.git

cd Compliance-Insights-using-Amazon-Q

sam deploy ---guided ---capabilities CAPABILITY_NAMED_IAM

```
**SAM Deployment parameters:**\
**Stack Name:** Name of the deployed AWS CloudFormation stack.

Eg: Stack Name : config-copy-stack

**AWS Region:** AWS Region where the stack will be deployed.

Eg: AWS Region : us-east-1

**Parameter SourceBucketArn**: Bucket ARN for Central AWS Config S3
Bucket in the Log account.

Eg: Parameter SourceBucketArn :
arn:aws:s3:::aws-controltower-logs-0987654321-us-east-1

**Parameter AccountList**: Provide a comma separated AWS account numbers
whose AWS config data will be extract into audit account.\
Eg: Parameter AccountList: 9999999999,8888888888

**Parameter RegionList :** Provide a comma separate list of AWS regions,
whose AWS Config data will be extracted into the audit account.

Eg: Parameter RegionList : us-east-1,eu-west-1

**Parameter SourceAccountId**: Provide the account id of the AWS
logarchive account in your organization where is the source of AWS
Config logs.\
Parameter SourceAccountId : 0987654321

### Step 3: Deploy and Configure Q Business

Amazon Q Business is a service that allows you to build intelligent
search and analytics applications on top of your business data. In this
example, we\'ll be using Q Business to analyze compliance-related data
stored in an S3 bucket.\
The [CloudFormation template attached](QBusiness.yml) in this solution created the following
resources:

1.  **Q Business Application**: The main application that will host our
    compliance analysis experience.

2.  **Q Business Index**: An index that the application will use to
    quickly search and retrieve relevant data.

3.  **Q Business Retriever**: Connects the application to the index,
    enabling search and retrieval functionality.

4.  **Q Business Data Source**: Configures an S3 bucket as the data
    source for the application. The S3 data source will be set to sync
    job to run at 8 AM every Monday in the UTC timezone.

5.  **Q Business Web Experience**: Provides a custom web interface for
    interacting with the Q Business application.

6.  **IAM Roles and Policies**: Grants the necessary permissions for the
    Q Business resources to access the S3 bucket and perform actions
    within the application.

Let\'s dive into the steps to deploy this solution.

**Deploy and Configure Q Business using a CloudFormation**

1.  Log in to the AWS Management Console and navigate to the
    CloudFormation service.

2.  Click \"Create stack\" and choose \"With new resources (standard)\".

3.  Select \"Upload a template file\" and choose the CloudFormation
    template you\'ve been provided.

4.  Fill in the required parameters:

    - **QBusinessApplicationName**: The name for your Amazon Q Business
      application.

    - **S3BucketName**: The name of the S3 bucket containing your
      compliance data.

    - **UseIDC**: Set to \"true\" if you want to use AWS IAM Identity
      Center for user authentication.

    - **UseIdP**: Set to \"true\" if you want to use an external
      Identity Provider (IdP) for user authentication.

    - **IdentityCenterArn**: The ARN of your IAM Identity Center
      instance (required if UseIDC is \"true\").

    - **ExternalIdPArn**: The ARN of your external IdP (required if
      UseIdP is \"true\").

<!-- -->

1.  Review the template and its parameters, then click \"Next\" to
    proceed.

2.  On the next page, configure any additional stack options as needed,
    then click \"Next\".

3.  Review the stack details and acknowledge any necessary capabilities,
    then click \"Create stack\" to deploy the resources.

The CloudFormation deployment should take a few minutes to complete.
Once the stack is in the \"CREATE_COMPLETE\" state, you can move on to
the next steps.

### Step 4: Assign Users and Groups

After the CloudFormation deployment, you\'ll need to manually assign
users and groups to the Q Business application. Here\'s how:

1.  In the AWS Console, navigate to the Amazon Q Business service.

2.  Click on the application name created by the template.

3.  In the \"User Access\" section, click \"Manage user access\".

4.  Click \"Add groups and users\", then select either \"Add and assign
    new users\" or \"Assign existing users and groups\" option.

5.  Provide the group/user name

6.  Select the group and click \"Assign\".

7.  Choose the appropriate subscription tier (e.g., Q Business Pro).

8.  Click \"Confirm\" to complete the assignment.

**Accessing the Q Business Web Experience**

After assigning users and groups, you can access the custom web
experience for your Q Business application. The CloudFormation template
outputs the URL for the web experience, which you can use to access the
application.\
The web experience provides a user-friendly interface for searching,
browsing, and interacting with the compliance data stored in your S3
bucket.

**Test the solution**

In order to test the solution, we will log in Amazon Q Business App
using login credentials. And interact using below questions:

1.  List all the non-compliant S3 buckets

![](images/Demo1.png)

2.  When was the bucket "name of the bucket" created and when did it
    turn non-compliant

![](images/Demo2.png)

3.  How can we remediate the non-compliant bucket "name of the bucket"

![](images/Demo3.png)

### Conclusion

By integrating AWS Config, Amazon S3, and Amazon Q Business, you can
unlock the power of natural language processing to gain valuable
insights into your AWS environment. This solution empowers your team
members to easily access and understand the configuration of their AWS
resources, regardless of their technical expertise. As your cloud
infrastructure evolves, this solution can help you stay on top of your
resource configurations and make informed decisions to optimize your AWS
environment.
