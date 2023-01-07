# AWS Service Now Connector Configuration

The repo has the cloudformation templates and the lambda function code to automate the IAM User creation, key rotation and additon of the IAM User Access and Secret Keys to the servicenow AWS Management connector's [account configuration](https://docs.aws.amazon.com/smc/latest/ag/sn-config-core-components.html#sn-configure-accounts).


## STEP 1: Setup the Parameter Store (Shared Services Account)

The lambda function reads the Servicenow API Authentication credentials from the parameters in the [AWS Systems Manager Parameter Store](https://docs.aws.amazon.com/systems-manager/latest/userguide/systems-manager-parameter-store.html).

Create below Paramters to store the Service now username, password.

1. Store the Servicenow api username in `/ServiceNow/${service_now_url}/username`
2. Store the password as a secret string in `/ServiceNow/${service_now_url}/password`

If your service now url is `https://d-xxxx.service-now.com`, then the ${Service_now_url} is just the `d-xxxx.service-now.com`.

## STEP 2: Deploy the lambda function (Shared Services Account)

Deploy the lambda function in the shared services account. The solution deploys the lambda function within a VPC. Please make sure the Subnet has [internet access](https://aws.amazon.com/premiumsupport/knowledge-center/internet-access-lambda-function/) as the custom resource lambda function connects to the service-now endpoint and AWS services.


### S3 bucket

Create a new [Amazon S3](https://docs.aws.amazon.com/AmazonS3/latest/userguide/Welcome.html) bucket using the instructions [here](https://docs.aws.amazon.com/AmazonS3/latest/userguide/create-bucket-overview.html) or use an existing bucket to store the lambda zip file.


### Build the lambda package
```
cd src/functions
mkdir -p ../build/
cp aws_client.py ../build
cp snow_client.py ../build
cp lambda_function.py ../build
pip install -r requirements.txt -t ../build
```

On Windows:
Open the build folder and select all -> Send to compressed file
Name the file as snowregister-v1.zip

Linux

```
cd ../build
zip -r snowregister-v1.zip .

# Upload the zip file to the S3 bucket
aws s3 cp snowregister-v1.zip s3://<bucket-name>/
cd ../..
rm -rf src/build
```

### Deploy the Lambda function (Shared Services)

Create a cloudformation stack from the template located at `src/templates/servicenow_connector_auto_register.yaml`. The template deploys the lambda function that will be used as a Custom resource.

Template Parameters:

VpcId - ID fo the VPC where the lambda function will be deployed. The VPC should have access to internet to make API calls to the Servicenow API.
SubnetList - Atleast two subnets within the VPC.
ManagementAccountId - Organization root account ID
OrganizationId - Organization ID

```
aws cloudformation deploy --stack-name service-now-automation \
--template-file src/templates/servicenow_connector_auto_register.yaml \
--parameter-overrides S3CodeBucket='<S3 Bucket Name>' \
VpcId='vpc-id-1' \
SubnetIdList='subnet-1,subnet-2' \
ManagementAccountId='111111111111' \
OrganizationID='o-xxxxxx' \
--region us-east-1 --capabilities CAPABILITY_NAMED_IAM
```

### Setup the Assume Role (Management Account)

The lambda function needs access to the Management to query the Organizations service to get the account name from the account ID. To achieve this, a role need to be created in the Management account and a trust need to be established between the lambda IAM execution role and the role in Management account.

Create a cloudfromation stack from the template `src/templates/servicenow_assume_role.yaml`

Parameters:
SourceRoleArn - This is the ARN of the Lambda exectuion IAM role deployed in the previous step.
ManagementAccountId - Organization root account ID

```
aws cloudformation deploy --stack-name service-now-lambda-assume-role-stack --template-file src/templates/servicenow_assume_role.yaml --region us-east-1 --parameter-overrides SourceRoleArn='{LAMBDA FUNCTION ARN}' ManagementAccountId='111111111111' --capabilities CAPABILITY_NAMED_IAM
```

## STEP 3: Deploy the Stackset (Delegated Admin or Management Account)

Deploy the stackset that creates the IAM Users in the Management account or the [delegated admin account](https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/stacksets-orgs-delegated-admin.html).

The stackset is created from the template `src/templates/servicenow_connector_global_config.yaml`.

The template requires the following parameters.

LambdaArn - This is the ARN of the Lambda funciton deployed in the Shared Service Account.
KeyVersion - The version number for the IAM user keys. Increment this value during key rotation step.
ServiceNowUrl - The service now instance URL.


Deploy the stackset for the IAM users
**Note:** Modify the stack-set name as requried.
```
aws cloudformation create-stack-set --stack-set-name service-snow-config --description "Deploys IAM User in the target OU and calls the custom resource to store the keys in service now" --template-body file://src/templates/servicenow_connector_global_config.yaml \
--parameters ParameterKey=LambdaArn,ParameterValue='<Lambda Function ARN>' \
ParameterKey=KeyVersion,ParameterValue=1 \
ParameterKey=ServiceNowUrl,ParameterValue='XXXXX.service-now.com' \
--capabilities CAPABILITY_NAMED_IAM \
--permission-model SERVICE_MANAGED \
--auto-deployment Enabled=true,RetainStacksOnAccountRemoval=false \
--call-as DELEGATED_ADMIN \
--managed-execution Active=false \
--region us-east-1
```

Add Target to the IAM Stackset. The stackset name should match the name from previous command. Replace the ou-XXXXXXX with the actual Organization Unit ID in the command below.
```
aws cloudformation create-stack-instances --stack-set-name service-snow-config \
--deployment-targets OrganizationalUnitIds='ou-XXXXXXX' \
--regions us-east-1 \
--call-as DELEGATED_ADMIN \
--region us-east-1
```

Deploy another stackset to create SQS queue for Security hub and Health Dashboard
**Note:** Modify the stack-set name as requried.
```
aws cloudformation create-stack-set --stack-set-name service-snow-config-regional \
--description "Deploys SQS queue for security hub and health dashboards" \
--template-body file://src/templates/servicenow_connector_regional_config.yaml \
--capabilities CAPABILITY_NAMED_IAM \
--permission-model SERVICE_MANAGED \
--auto-deployment Enabled=true,RetainStacksOnAccountRemoval=false \
--call-as DELEGATED_ADMIN \
--managed-execution Active=false \
--region us-east-1
```

Add Target to the above stackset. The stackset name should match the above. Replace the ou-XXXXXXX with the actual Organization Unit ID in the command below.

```
aws cloudformation create-stack-instances --stack-set-name service-snow-config-regional \
--deployment-targets OrganizationalUnitIds='ou-XXXXXXX' \
--regions us-east-1 \
--call-as DELEGATED_ADMIN \
--region us-east-1
```

To integrate the AWS Support, deploy another stackset for the Support Queue as requried by the connector (4.5.0)
**Note:** Modify the stack-set name as requried.
```
aws cloudformation create-stack-set --stack-set-name service-snow-config-support \
--description "Deploys SQS queue for AWS Support integration" \
--template-body file://src/templates/servicenow_connector_support_queue.yaml \
--capabilities CAPABILITY_NAMED_IAM \
--permission-model SERVICE_MANAGED \
--auto-deployment Enabled=true,RetainStacksOnAccountRemoval=false \
--call-as DELEGATED_ADMIN \
--managed-execution Active=false \
--region us-east-1
```

Add Target to the regional stackset. The stackset name should match the above. Replace the ou-XXXXXXX with the actual Organization Unit ID in the command below.

```
aws cloudformation create-stack-instances --stack-set-name service-snow-config-support \
--deployment-targets OrganizationalUnitIds='ou-XXXXXXX' \
--regions us-east-1 \
--call-as DELEGATED_ADMIN \
--region us-east-1
```

## Rotating the Keys

As a security best practice, the IAM User keys should be rotated on a schedule to reduce the risk of compromised keys. To rotate the keys, make an update to the `service-snow-config` stackset by updating the KeyVersion parameter. Increment the KeyVersion and execute the update-stack-set command. The command is similar to the create. Replace `create-stack-set` with `update-stack-set` and execute the same command. The `create-stack-instance` is NOT required to be executed for the key rotation.


## Updating the Connector and the AWS template
The updated version of the connector might require an update on the existing cloudformation template `servicenow_connector_config.yaml`. The AWS Documentation https://docs.aws.amazon.com/servicecatalog/latest/smcguide/sn-base-perms.html has links to the latest cloudformation template. If the template needs to be updated, update the `servicenow_connector_config.yaml` with the new template.

The default template in the AWS documentation is not production ready. In this solution, we have broken down the template based on the regional and non-regional resources to be able to deploy via Stackset across multiple regions.

The default template is customized as shown below to utilize the custom resource lambda.

```
  ServiceNowUrl:
    Type: String
    Description: Service Now instance url ex. d-XXXXX.service-now.com
  LambdaArn:
    Type: String
    Description: Service now customr resource Lambda function arn
  KeyVersion:
    Type: String
    Description: Increment the key version to update the
```

```
  SCEndUserAccessKeys:
    DependsOn: SCEndUser
    Properties:
      Serial: !Ref KeyVersion      <-- Included the serial property to the End user access key
      Status: Active
      UserName: !Ref SCEndUserName
    Type: AWS::IAM::AccessKey

  SCSyncUserAccessKeys:
    DependsOn: SCSyncUser
    Properties:
      Serial: !Ref KeyVersion     <-- Included the serial property to the Sync user access key
      Status: Active
      UserName: !Ref SCSyncUserName
    Type: AWS::IAM::AccessKey
```


Added the below resource under the resource section to update the Access and Secret Access Keys into Service Now.
The custom resource properties provide flags to enable the integrations to AWS Services.

```
RegisterSerNow:
    Type: Custom::ServiceNowReg
    Properties:
      ServiceToken: !Ref LambdaArn
      Region: !Ref "AWS::Region"
      AccountId: !Ref AWS::AccountId
      KeyVersion: !Ref KeyVersion
      ServiceNowUrl: !Ref ServiceNowUrl
      SyncUserName: !Ref SCSyncUserName
      EndUserName: !Ref SCEndUserName
      SCEndUser:
        UserName: !Ref SCEndUserName
        AccessKey: !Ref 'SCEndUserAccessKeys'
        SecretAccessKey: !GetAtt 'SCEndUserAccessKeys.SecretAccessKey'
      SCSyncUser:
        UserName: !Ref SCSyncUserName
        AccessKey: !Ref 'SCSyncUserAccessKeys'
        SecretAccessKey: !GetAtt 'SCSyncUserAccessKeys.SecretAccessKey'
      EnableSystemsManager: False    # Enable/disable AWS Systems Manager integration
      EnableChangeManager: False     # Enable/Disable AWS System Manager Change Manager integration
      EnableOpsCenter: False         # Enable/Disable AWS OpsCenter integration
      EnableServiceCatalog: False    # Enable/Disable Service Catalog Integration
      EnableConfig: False            # Enable/Disable Config Integration
      EnableAwsSupport: False        # Enable/Disable AWS Support Integration
      EnableSecurityHub: False       # Enable/Disable Security Hub Integration
      EnableHealthDashboard: False   # Enable/Disable Health Dashboard Integration
      EnableIncidentManager: False   # Enable/Disable incident Manager Integration
      EnableRegions:                 # List of regions to set in the service now account
        - us-east-1
      Tags:
        - Key: App_Name
          Value: Service_Now_connector
      StoreKeys: False              # Enable this flag to backup the AWS Access key and secret keys in secrets manager
```

## Multi Region support
The solution supports multi region deployments as well. The `servicenow_connector_global_config.yaml` deploys only IAM related resources and doesn't need to be deployed in multiple regions. But the other regional templates that deploys the SQS need to be deployed across multiple regions. To add new region, add new stackset instances using the same `create-stack-instances` with new list of regions to add. 


## New AWS Account
The stackset is set to deploy instances targeting an Organization Unit. The deployment permission model is SERVICE_MANAGED. This ensures
that anytime a new account gets added to the target Org Units, the stackset will autmatically create a new stack-instance in the new account.

## Deleting an AWS Account
Removing an account from an OU automatically triggers the stackset to delete the stack instance from the account. The account from the Service Now is NOT removed automatically.


## AWS Docuemntation links
* Service Management Connector Release notes: https://docs.aws.amazon.com/servicecatalog/latest/smcguide/sn-release-notes.html
* Service Management Connector Baseline template: https://docs.aws.amazon.com/servicecatalog/latest/smcguide/sn-base-perms.html
* AWS Cloudformation Custom Resource: https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/template-custom-resources.html
* AWS Lambda Deployment(Python): https://docs.aws.amazon.com/lambda/latest/dg/python-package.html
* AWS CLI Reference - https://docs.aws.amazon.com/cli/latest/reference/cloudformation/index.html#cli-aws-cloudformation

## Security

See [CONTRIBUTING](CONTRIBUTING.md#security-issue-notifications) for more information.

## License

This library is licensed under the MIT-0 License. See the LICENSE file.

