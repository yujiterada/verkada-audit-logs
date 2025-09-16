from dotenv import load_dotenv
import logging
import os
import requests
import time
from typing import Optional, Dict, Any, Generator

VERKADA_ENVIRONMENT_VARIABLE_API_KEY = "VERKADA_API_KEY"
DEFAULT_BASE_URL = "https://api.au.verkada.com"
DEFAULT_SESSION_TIMEOUT = 30
WAIT_ON_RATE_LIMIT = True
NGINX_429_RETRY_WAIT_TIME = 10
MAX_RETRIES = 3

load_dotenv()

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class VerkadaAuthenticationError(Exception):
    """Exception for authentication errors"""
    pass

class VerkadaSession:
    """Session class for handling HTTP requests with retries and error handling"""

    def __init__(self, timeout=DEFAULT_SESSION_TIMEOUT):
        self.session = requests.Session()
        self.timeout = timeout
        self.max_retries = MAX_RETRIES

    def request(self, method, url, **kwargs):
        retries = self.max_retries

        while retries > 0:
            try:
                response = self.session.request(method=method, url=url, timeout=self.timeout, **kwargs)
                print(response)
                if response:
                    response.close()
                    reason = response.reason if response.reason else ''
                    status = response.status_code
            except requests.exceptions.RequestException as e:
                print(e)
                retries -= 1
                time.sleep(1)

            match status:
                case status if 200 <= status < 300:
                    return response
                case 409:
                    raise VerkadaAuthenticationError(f"Authentication error: Bad API key or token")
                case 429:
                    logger.warning(f"Rate limit hit, waiting {NGINX_429_RETRY_WAIT_TIME} seconds...")
                    time.sleep(NGINX_429_RETRY_WAIT_TIME)
                    retries -= 1
                    response = self.session.request(method, url, **kwargs)
                case status if 500 <= status:
                    print((f'{{method}} {url} - {status} {reason}'))
                    retries -= 1
                case status if status != 429 and 400 <= status < 500:
                    retries -= 1

class VerkadaAPI():
    def __init__(self, api_key=None):
        self.api_key = None
        self.token = None
        self.session = VerkadaSession()

        if not api_key and not os.environ.get(VERKADA_ENVIRONMENT_VARIABLE_API_KEY):
            print("API key not found")
            return
        self.api_key = api_key or os.environ.get(VERKADA_ENVIRONMENT_VARIABLE_API_KEY)
        res = self.postLoginApiKeyViewV2()
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
        headers = {
            "x-api-key": f"{self.api_key}",
            "Content-Type": "application/json",
        }
        response = self.session.request('POST', url, headers=headers)
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
        response = self.session.request('GET', url, headers=headers)
        return response

if __name__ == "__main__":
    # Create an instance of VerkadaAPI to test
    client = VerkadaAPI()
    res = client.getAuditLogsViewV1()
    print(res.json())