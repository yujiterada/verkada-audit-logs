from dotenv import load_dotenv
import logging
import os
import requests
import time
from typing import Optional, Dict, Any, Generator
from requests.exceptions import ConnectionError, Timeout, RequestException

VERKADA_ENVIRONMENT_VARIABLE_API_KEY = "VERKADA_API_KEY"
DEFAULT_BASE_URL = "https://api.au.verkada.com"
DEFAULT_SESSION_TIMEOUT = 30
DEFAULT_PAGE_SIZE = 1
WAIT_ON_RATE_LIMIT = True
RETRY_WAIT_TIME = 10
MAX_RETRIES = 3

load_dotenv()
# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def clean_params(params):
    """Remove keys with None values"""
    return {k: v for k, v in params.items() if v is not None}

class VerkadaAuthenticationError(Exception):
    """Exception for authentication errors"""
    pass

class VerkadaTokenExpiredError(Exception):
    """Exception for token expired errors"""
    pass

class VerkadaConnectionError(Exception):
    """Exception for connection errors"""
    pass

class VerkadaSession:
    """Session class for handling HTTP requests with retries and error handling"""

    def __init__(self, timeout=DEFAULT_SESSION_TIMEOUT):
        self.session = requests.Session()
        self.timeout = timeout
        self.max_retries = MAX_RETRIES

    def request(self, method, url, **kwargs):
        retries = self.max_retries
        last_exception = None

        while retries > 0:
            try:
                logger.info(f"Making {method} request to {url} (retries left: {retries})")
                response = self.session.request(method=method, url=url, timeout=self.timeout, **kwargs)
                status = response.status_code
                reason = response.reason if response.reason else ''
                
                # Handle successful response
                if 200 <= status < 300:
                    logger.info(f"Request successful: {status}")
                    return response
                if status == 401:
                    raise VerkadaTokenExpiredError(f"Token expired")
                elif status == 409:
                    raise VerkadaAuthenticationError(f"Authentication error: Bad API key or token")
                elif status == 429:
                    logger.warning(f"Rate limit hit, waiting {RETRY_WAIT_TIME} seconds...")
                    time.sleep(RETRY_WAIT_TIME)
                    retries -= 1
                    continue
                elif 500 <= status:
                    logger.warning(f"Server error {status} {reason} for {method} {url}")
                    retries -= 1
                    if retries > 0:
                        wait_time = (self.max_retries - retries) * RETRY_WAIT_TIME  # Exponential backoff
                        logger.info(f"Retrying in {wait_time} seconds...")
                        time.sleep(wait_time)
                    continue
                elif 400 <= status < 500:
                    logger.warning(f"Client error {status} {reason} for {method} {url}")
                    retries -= 1
                    if retries > 0:
                        wait_time = (self.max_retries - retries) * RETRY_WAIT_TIME
                        logger.info(f"Retrying in {wait_time} seconds...")
                        time.sleep(wait_time)
                    continue
                    
            except (ConnectionError, Timeout) as e:
                last_exception = e
                logger.warning(f"Connection error: {e}")
                retries -= 1
                if retries > 0:
                    wait_time = (self.max_retries - retries) * RETRY_WAIT_TIME  # Exponential backoff
                    logger.info(f"Retrying in {wait_time} seconds...")
                    time.sleep(wait_time)
                continue
            except RequestException as e:
                last_exception = e
                logger.warning(f"Request error: {e}")
                retries -= 1
                if retries > 0:
                    wait_time = (self.max_retries - retries) * RETRY_WAIT_TIME
                    logger.info(f"Retrying in {wait_time} seconds...")
                    time.sleep(wait_time)
                continue
            except Exception as e:
                logger.error(f"Unexpected error: {e}")
                raise e

        # If we get here, all retries failed
        if last_exception:
            if isinstance(last_exception, (ConnectionError, Timeout)):
                raise VerkadaConnectionError(f"Failed to connect after {self.max_retries} retries: {last_exception}")
            else:
                raise last_exception
        else:
            raise VerkadaConnectionError(f"Request failed after {self.max_retries} retries")

class VerkadaAPI():
    def __init__(self, api_key=None):
        self.api_key = None
        self.token = self._readToken()
        self.session = VerkadaSession()

        if not api_key and not os.environ.get(VERKADA_ENVIRONMENT_VARIABLE_API_KEY):
            logger.error("API key not found")
            return
        self.api_key = api_key or os.environ.get(VERKADA_ENVIRONMENT_VARIABLE_API_KEY)
        
        try:
            if not self.token:
                token = self._refreshToken()
        except VerkadaTokenExpiredError as e:
            logger.error(f"Token expired during authentication: {e}")
            token = self._refreshToken()
            self.token = token
        except VerkadaConnectionError as e:
            logger.error(f"Connection error during authentication: {e}")
            raise
        except VerkadaAuthenticationError as e:
            logger.error(f"Authentication error: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error during authentication: {e}")
            raise

    def _refreshToken(self):
        res = self.postLoginApiKeyViewV2()
        self.token = res.json()['token']
        with open('token.txt', 'w') as f:
            f.write(self.token)
        logger.info("Token refreshed and saved to token.txt")
        return self.token

    def _readToken(self):
        logger.info("Reading token from token.txt")
        if not os.path.exists('token.txt'):
            logger.info("Token file not found, creating new token")
            return None
        with open('token.txt', 'r') as f:
            self.token = f.read()
        return self.token

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
                        page_size: Optional[int] = DEFAULT_PAGE_SIZE) -> Generator[Dict[str, Any], None, None]:
        """
        Generator function to retrieve all audit logs across multiple pages.

        Args:
            start_time (int, optional): Start of time range as Unix timestamp in seconds.
            end_time (int, optional): End of time range as Unix timestamp in seconds.
            page_size (int, optional): Number of items per page (1-200, default: 200).

        Yields:
            Individual audit log entries
        """
        query_params = {'start_time': start_time, 'end_time': end_time, 'page_size': page_size}
        clean_query_params = clean_params(query_params)
        resource = f'/core/v1/audit_log'
        url = f"{DEFAULT_BASE_URL}{resource}"
        headers = {
            "x-verkada-auth": f"{self.token}",
            "Content-Type": "application/json"
        }
        response = self.session.request('GET', url, headers=headers, params=clean_query_params)
        return response

if __name__ == "__main__":
        # Create an instance of VerkadaAPI to test
    client = VerkadaAPI()
    res = client.getAuditLogsViewV1()
    print(res.json())