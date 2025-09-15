from dotenv import load_dotenv
import logging
import os
import requests
from typing import Optional, Dict, Any, Generator

VERKADA_ENVIRONMENT_VARIABLE_API_KEY = "VERKADA_API_KEY"
DEFAULT_BASE_URL = "https://api.au.verkada.com"

load_dotenv()

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class VerkadaAPI():
    def __init__(self, api_key=None):
        if not api_key and not os.environ.get(VERKADA_ENVIRONMENT_VARIABLE_API_KEY):
            print("API key not found")
            return

        self.api_key = api_key or os.environ.get(VERKADA_ENVIRONMENT_VARIABLE_API_KEY)
        res = self.postLoginApiKeyViewV2()
        print(res.json())
        self.token = res.json()['token']

    def postLoginApiKeyViewV2(self):
        """
        API Tokens are required to make requests to any Verkada API endpoints with the exception of the Get Streaming Token endpoints, which requires a top-level API Key for authentication, as well as the Stream Footage (live or historical) API that requires a JSON Web Token (JWT).
        API Tokens inherit permissions from the top-level API key used to generate them and will be limited to that same permission scope. If the API Key used to generate an API Token only has Camera Read-Only permissions, then the associated API Token would only be authorized to call Camera GET endpoints.
        API Tokens are valid for 30 minutes and cannot be refreshed. Users will need to call the Get API Token endpoint again to retrieve a new Token if their previous one has expired. When making a call using an expired API Token, users will receive a 401 Authentication Error as well as the following error message:
        {'id': '0e2d', 'message': 'Token expired', 'data': None}
        """
        resource = f'/token'
        url = f"{DEFAULT_BASE_URL}{resource}"
        print(url)
        headers = {
            "x-api-key": f"{self.api_key}",
            "Content-Type": "application/json",
        }
        response = requests.post(url, headers=headers)
        return response
    
    def getAuditLogsViewV1(self,
                        start_time: Optional[int] = None,
                        end_time: Optional[int] = None,
                        page_size: Optional[int] = 100) -> Generator[Dict[str, Any], None, None]:
        """
        Generator function to retrieve all audit logs across multiple pages.
        
        Args:
            start_time (int, optional): Start of time range as Unix timestamp in seconds.
            end_time (int, optional): End of time range as Unix timestamp in seconds.
            page_size (int, optional): Number of items per page (1-200, default: 200).
        
        Yields:
            Individual audit log entries
        """
        resource = f'/core/v1/audit_log'
        url = f"{DEFAULT_BASE_URL}{resource}"
        headers = {
            "x-verkada-auth": f"{self.token}",
            "Content-Type": "application/json"
        }
        response = requests.get(url, headers=headers)
        return response
        
        # while True:
        #     response = self.get_audit_logs(
        #         start_time=start_time,
        #         end_time=end_time,
        #         page_token=page_token,
        #         page_size=page_size
        #     )
            
        #     if not response:
        #         logger.error("Failed to retrieve audit logs page")
        #         break
            
        #     # Yield individual audit log entries
        #     # Note: Adjust based on actual response structure
        #     audit_logs = response.get('audit_logs', [])
        #     for log in audit_logs:
        #         yield log
            
        #     # Check if there are more pages
        #     page_token = response.get('next_page_token')
        #     if not page_token:
        #         break

if __name__ == "__main__":
    # Create an instance of VerkadaAPI to test
    client = VerkadaAPI()
    res = client.getAuditLogsViewV1()
    print(res.json())