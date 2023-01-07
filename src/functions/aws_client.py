''' Initialize aws clients for use in the lambda fucntion '''

import logging
import boto3
import os

logger = logging.getLogger()
DEFAULT_REGION = boto3.session.Session().region_name
assume_role_name = os.getenv('DELEGATED_ADMIN_ASSUME_ROLE_NAME')
assume_role_acc_id = os.getenv('DELEGATED_ADMIN_ASSUME_ROLE_ACC_ID')


class AwsClients:
    ''' Defines the AWS clients and functions to handle AWS operations '''
    def __init__(self):
        self._active_region = DEFAULT_REGION
        self._ssm_client = boto3.client('ssm',self._active_region)
        self._iam_client = boto3.client('iam',self._active_region)
        self._org_client = boto3.client('organizations', self._active_region)
        self._sm_client = boto3.client('secretsmanager', self._active_region)
        self._sts_client = boto3.client('sts', self._active_region)

    def ssm_get_parameter(self, param_path):
        """
        param_path: ssm parameter path
        return: ssm parameter value
        """
        logger.info(f"Get the parameter value for path {param_path}")
        resp = self._ssm_client.get_parameter(
            Name=param_path,
            WithDecryption=True
        )
        logger.debug(resp)
        return resp['Parameter']['Value']

    def get_account_name(self, account_id):
        """
        account_id: AWS Account number
        retrun: AWS Account name
        """
        logger.info(f"Get the account name for the account id: {account_id}")
        logger.info("Assume to the Management account")

        if assume_role_name != "None" and assume_role_acc_id != "None":
            sts_response = self._sts_client.assume_role(
                RoleArn=f"arn:aws:iam::{assume_role_acc_id}:role/{assume_role_name}",
                RoleSessionName='servicenow-lambda'
            )

            assume_creds = sts_response['Credentials']

            self._org_client = boto3.client('organizations', self._active_region,
                aws_access_key_id=assume_creds['AccessKeyId'],
                aws_secret_access_key=assume_creds['SecretAccessKey'],
                aws_session_token=assume_creds['SessionToken']
            )
        else:
            self._org_client = boto3.client('organizations', self._active_region)

        response = self._org_client.describe_account(
            AccountId=account_id
        )

        logger.debug(response)
        logger.info(f"Account name found: {response['Account']['Name']}")
        return response['Account']['Name']

    def store_secret(self, user_name, account_name, access_keys,
                     secret_access_keys, version, tags, kmsid):
        """
        Store a copy of the IAM user keys before calling the snow api
        """
        logger.info(f"Storing the secret for user {user_name}")
        self._sm_client.create_secret(
            Name=f'/servicenow/{user_name}/{account_name}/{version}',
            Description=f'IAM secret for account {account_name}',
            KmsKeyId=kmsid,
            SecretString=f'{{"{access_keys}":"{secret_access_keys}"}}',
            Tags=tags
        )

    def remove_previous_secret(self, user_name, account_name, version):
        logger.info("List the existing secrets")
        paginator = self._sm_client.get_paginator('list_secrets')
        page_iterator = paginator.paginate()
        for page in page_iterator:
            for secret in page['SecretList']:
                if secret['Name'] == f"/servicenow/{user_name}/{account_name}/{version}":
                    logger.info("Previous version of secret found. Deleting the previous secret")
                    secret_arn = secret['ARN']
                    logger.info(f"Deleting the secret version {secret_arn}")
                    self._sm_client.delete_secret(
                        SecretId=secret_arn,
                        RecoveryWindowInDays=14
                    )
        return
