''' Service Now API Request module '''
import json
import logging
import urllib3

logger = logging.getLogger()
http = urllib3.PoolManager()
SNOW_TABLE_NAME="x_126749_aws_sc_account"
SNOW_REGION_TABLE_NAME = "x_126749_aws_sc_account_sync"

class SnowApi:
    ''' Class for Service Now API actions '''
    def __init__(self, aws_client, user_keys, aws_account_id, integrations, url):
        # get the url base
        self._sys_id = None
        self.old_data = None
        self.account_is_new = None
        self.accountid = aws_account_id
        self.snow_account_name = aws_client.get_account_name(aws_account_id)
        self.snow_url = url
        self.snow_user = aws_client.ssm_get_parameter(f"/ServiceNow/{url}/username")
        self.snow_passwd = aws_client.ssm_get_parameter(f"/ServiceNow/{url}/password")
        self.user_keys = user_keys
        self.service_integrations = integrations

    def _build_body(self):
        ''' Build the request body and headers '''
        logger.info("Build the request body for service new api call")
        resp_body = {
            "awsname": self.snow_account_name,
            "awsaccountnumber": self.accountid,
            "awsaccesskeyenduser": self.user_keys["SCEndUser"]["AccessKeyId"],
            "awssecretaccesskeyenduser": self.user_keys["SCEndUser"]["SecretAccessKey"],
            "awsaccesskeysyncuser": self.user_keys["SCSyncUser"]["AccessKeyId"],
            "awssecretaccesskeysyncuser": self.user_keys["SCSyncUser"]["SecretAccessKey"],
            "awsenablesystemsmanager": self.service_integrations["EnableSystemsManager"],
            "awsenablechangemanager": self.service_integrations["EnableChangeManager"],
            "awsenableopscenter": self.service_integrations["EnableOpsCenter"],
            "awsenableservicecatalog": self.service_integrations["EnableServiceCatalog"],
            "awsenableconfig": self.service_integrations["EnableConfig"],
            "awsenablesupport": self.service_integrations["EnableAwsSupport"],
            "awsenablesecurityhub": self.service_integrations["EnableSecurityHub"],
            "awsenablehealthdashboard": self.service_integrations["EnableHealthDashboard"],
            "awsenableincidentmanager": self.service_integrations["EnableIncidentManager"]
        }
        return resp_body

    def _build_region_body(self, region):
        ''' Build the request body for region table '''
        logger.info(f"Build regions table api request body for {region}")
        resp_body = {
            "awsaccount": self._sys_id,
            "awsregion": region
        }
        return resp_body

    def _do_request(self, url, action, body=None):
        ''' Call the Snow Api '''
        logger.info(f"Sending the {action} request to Servicenow url {url}")
        authstr = f"{self.snow_user}:{self.snow_passwd}"
        headers = {'content-type' : 'application/json','Accept' : 'application/json'}
        headers.update(urllib3.make_headers(basic_auth=authstr))
        logger.debug(headers)
        req_body = ""
        response = None

        if body is not None:
            req_body = json.dumps(body)

        try:
            response = http.request(action,url,body=req_body.encode('utf-8'),headers=headers,timeout=10)
            logger.info("Logging the response")
            logger.info(response.status)
            logger.info(response.reason)
        except urllib3.exceptions.MaxRetryError:
            logger.error(f'Error connecting to the Service Now Url {url}.')
            raise Exception(f'Error connecting to the Service Now Url {url}.')

        if response.status not in [200, 201, 204]:
            error_msg = response.reason
            raise Exception(f"Service now request failed with {error_msg}.")

        return response

    def get_account(self):
        '''
            retrieve sys_id associated with account from service now table
        '''
        full_url = f"https://{self.snow_url}/api/now/table/{SNOW_TABLE_NAME}?" \
                   f"sysparm_query=awsaccountnumber={self.accountid}&sysparm_limit=1"
        logger.info(f'Get existing account info from {full_url}')
        resp = self._do_request(full_url, "GET")
        if resp is not None:
            jresp = json.loads(resp.data.decode('utf-8'))
            # check if account exists
            if len(jresp["result"]) > 0:
                self.old_data = jresp["result"][0]
                self._sys_id = self.old_data["sys_id"]
                logger.info(f"Existing account sys_id: {self._sys_id}")
                logger.debug("Old Data:")
                logger.debug(self.old_data)
            return jresp
        return None

    def insert_region(self, region):
        '''
            Call this function to insert the regions
        '''
        logger.info(f"Inserting region {region}")
        account_info = self.get_account()
        full_url = f"https://{self.snow_url}/api/now/table/{SNOW_REGION_TABLE_NAME}"
        if account_info:
            body = self._build_region_body(region)
            resp = self._do_request(full_url, "POST", body)
            logger.info(f"Status: {resp.status}, Reason: {resp.reason}, Response {resp.data}")
        else:
            raise f"Account {self.snow_account_name} not configured in service now"

    def delete_region(self, region):
        '''
            Call this function to remove a region
        '''
        logger.info(f"Delete the region {region}")
        full_url = f"https://{self.snow_url}/api/now/table/{SNOW_REGION_TABLE_NAME}"
        query_url = f"{full_url}?sysparm_query=awsaccount={self._sys_id}&awsregion={region}"
        response = self._do_request(query_url, "GET")
        json_data = json.loads(response.data.decode('utf-8'))
        for re in json_data['result']:
            del_url = f"{full_url}/{re['sys_id']}"
            response = self._do_request(del_url, "DELETE")
            print(f"Delete Status: {response.status} {response.reason}")

    def update_region(self):
        '''
            Call this function to update the region table
        '''
        account_info = self.get_account()
        if account_info:
            previous_region_list = self.service_integrations['old_properties']['EnableRegions']
            to_add = set(self.service_integrations['EnableRegions']) - set(previous_region_list)
            to_delete = set(previous_region_list) - set(self.service_integrations['EnableRegions'])

            # Add the regions
            for region in list(to_add):
                self.insert_region(region)

            # Delete the regions
            for region in list(to_delete):
                self.delete_region(region)
        else:
            raise f"Account {self.accountid} not configured in service now"

    def insert_account(self):
        '''
            Call this function to insert the SCEndUser and SCSyncUser
            user keys into service now
        '''
        logger.info("Add new account in Service Now")
        #POST https://XXXX.service-now.com/api/now/table/x_126749_aws_sc_account
        full_url = f"https://{self.snow_url}/api/now/table/{SNOW_TABLE_NAME}"
        body = self._build_body()
        resp = self._do_request(full_url, "POST", body)

        # Add region to the accounts
        for region in self.service_integrations['EnableRegions']:
            self.insert_region(region)
        return


    def update_account(self):
        '''
            Call this function to update the SCEndUser and SCSyncUser
            xuser keys into service now
        '''
        #PUT https://XXXX.service-now.com/api/now/table/x_126749_aws_sc_account/{sys_id}
        # check for sysid first?
        logger.info("Update existing account in Service Now")

        # Set the Sys id
        self.get_account()

        logger.info(self._sys_id)
        #Build the full url
        full_url = f"https://{self.snow_url}/api/now/table/{SNOW_TABLE_NAME}/{self._sys_id}"
        body = self._build_body()
        resp = self._do_request(full_url, "PUT", body)

        # Update the regions data
        self.update_region()
        return resp.data