from ssl import ALERT_DESCRIPTION_UNSUPPORTED_EXTENSION
from threading import activeCount
from aws_client import AwsClients
from snow_client import SnowApi
import sys
import logging
from crhelper import CfnResource
import os

# WARNING - Changing the log_level from INFO to DEBUG will expose the keys in cloud watch logs.
helper = CfnResource(json_logging=False, log_level='INFO', boto_level='CRITICAL', sleep_on_delete=120, ssl_verify=None)

logger = logging.getLogger()
logger.setLevel(logging.INFO)
logging.getLogger().addHandler(logging.StreamHandler(sys.stdout))

KMS_KEY = os.getenv('SECRETS_KMS_KEY')
END_USER_NAME = os.getenv('END_USER_NAME')
SYNC_USER_NAME = os.getenv('SYNC_USER_NAME')

def get_keys(event):
    logger.info("Extracting Keys from event and restructure it")
    user_keys = {}
    try:
        user_keys.update(
            {
                "SCEndUser" : {
                    "AccessKeyId": event['ResourceProperties']['SCEndUser']['AccessKey'],
                    "SecretAccessKey": event['ResourceProperties']['SCEndUser']['SecretAccessKey']
                },
                "SCSyncUser": {
                    "AccessKeyId": event['ResourceProperties']['SCSyncUser']['AccessKey'],
                    "SecretAccessKey": event['ResourceProperties']['SCSyncUser']['SecretAccessKey']
                }
            }
        )
    except KeyError as e:
        raise KeyError(e)
    return user_keys


def set_integration_flags(event):
    integrations = {}
    if 'EnableSystemsManager' not in event['ResourceProperties']:
        integrations["EnableSystemsManager"] = False
    else:
        integrations['EnableSystemsManager'] = event['ResourceProperties']['EnableSystemsManager']

    if 'EnableChangeManager' not in event['ResourceProperties']:
        integrations['EnableChangeManager'] = False
    else:
        integrations['EnableChangeManager'] = event['ResourceProperties']['EnableChangeManager']

    if 'EnableOpsCenter' not in event['ResourceProperties']:
        integrations['EnableOpsCenter'] = False
    else:
        integrations['EnableOpsCenter'] = event['ResourceProperties']['EnableOpsCenter']

    if 'EnableServiceCatalog' not in event['ResourceProperties']:
        integrations['EnableServiceCatalog'] = False
    else:
        integrations['EnableServiceCatalog'] = event['ResourceProperties']['EnableServiceCatalog']

    if 'EnableConfig' not in event['ResourceProperties']:
        integrations['EnableConfig'] = False
    else:
        integrations['EnableConfig'] = event['ResourceProperties']['EnableConfig']

    if 'EnableAwsSupport' not in event['ResourceProperties']:
        integrations['EnableAwsSupport'] = False
    else:
        integrations['EnableAwsSupport'] = event['ResourceProperties']['EnableAwsSupport']

    if 'EnableSecurityHub' not in event['ResourceProperties']:
        integrations['EnableSecurityHub'] = False
    else:
        integrations['EnableSecurityHub'] = event['ResourceProperties']['EnableSecurityHub']

    if 'EnableHealthDashboard' not in event['ResourceProperties']:
        integrations['EnableHealthDashboard'] = False
    else:
        integrations['EnableHealthDashboard'] = event['ResourceProperties']['EnableHealthDashboard']

    if 'EnableIncidentManager' not in event['ResourceProperties']:
        integrations['EnableIncidentManager'] = False
    else:
        integrations['EnableIncidentManager'] = event['ResourceProperties']['EnableIncidentManager']

    if "EnableRegions" not in event['ResourceProperties']:
        integrations['EnableRegions'] = []
    else:
        if isinstance(event['ResourceProperties']['EnableRegions'], list):
            integrations['EnableRegions'] = event['ResourceProperties']['EnableRegions']
        else:
            raise("EnableRegions should be of type list")
    return integrations


@helper.create
def create(event, context):
    logger.info("Create Event..")
    try:
        aws = AwsClients()
        user_keys = get_keys(event)
        accountid = event['ResourceProperties']['AccountId']
        integrations = set_integration_flags(event)
        key_version = event['ResourceProperties']['KeyVersion']
        tags = event['ResourceProperties']['Tags']
        end_user = event['ResourceProperties']['EndUserName']
        sync_user = event['ResourceProperties']['SyncUserName']
        logger.info(integrations)

        url = event['ResourceProperties']['ServiceNowUrl']
        snow = SnowApi(aws, user_keys, accountid, integrations, url)

        if event['ResourceProperties']['StoreKeys'] == 'true':
            # Store the end user credentials in the Secrets manager
            aws.store_secret(
                end_user,
                snow.snow_account_name,
                snow.user_keys['SCEndUser']['AccessKeyId'],
                snow.user_keys['SCEndUser']['SecretAccessKey'],
                key_version,
                tags,
                KMS_KEY
            )

            # Store the sync user credentials in the Secrets manager
            aws.store_secret(
                sync_user,
                snow.snow_account_name,
                snow.user_keys['SCSyncUser']['AccessKeyId'],
                snow.user_keys['SCSyncUser']['SecretAccessKey'],
                key_version,
                tags,
                KMS_KEY
            )

        # Insert the keys into Service Now Connector
        snow.insert_account()

    except KeyError as e:
        raise Exception(e)
    return


@helper.update
def update(event, context):
    logger.info("Update Event..")
    try:
        aws = AwsClients()
        user_keys = get_keys(event)
        accountid = event['ResourceProperties']['AccountId']
        integrations = set_integration_flags(event)
        key_version = event['ResourceProperties']['KeyVersion']
        tags = event['ResourceProperties']['Tags']
        end_user = event['ResourceProperties']['EndUserName']
        sync_user = event['ResourceProperties']['SyncUserName']
        aws = AwsClients()
        user_keys = get_keys(event)
        accountid = event['ResourceProperties']['AccountId']
        url = event['ResourceProperties']['ServiceNowUrl']
        integrations['old_properties'] = event['OldResourceProperties']
        snow = SnowApi(aws, user_keys, accountid, integrations, url)

        if event['ResourceProperties']['StoreKeys'] == 'true':
            # Store the end user credentials in the Secrets manager
            aws.store_secret(
                end_user,
                snow.snow_account_name,
                snow.user_keys['SCEndUser']['AccessKeyId'],
                snow.user_keys['SCEndUser']['SecretAccessKey'],
                key_version,
                tags,
                KMS_KEY
            )

            # Store the sync user credentials in the Secrets manager as a backup
            aws.store_secret(
                sync_user,
                snow.snow_account_name,
                snow.user_keys['SCSyncUser']['AccessKeyId'],
                snow.user_keys['SCSyncUser']['SecretAccessKey'],
                key_version,
                tags,
                KMS_KEY
            )
            previous_version = int(key_version) - 1
            aws.remove_previous_secret('SCEndUser', snow.snow_account_name, previous_version)
            aws.remove_previous_secret('SCSyncUser', snow.snow_account_name, previous_version)

        #Update the account in service now with new credentials
        snow.update_account()

    except KeyError as e:
        raise Exception(e)
    return

@helper.delete
def delete(event, context):
    return


def handler(event, context):
    if 'StackId' in event:
        helper(event, context)
    else:
        print("Called Outside of the cloudformation")


