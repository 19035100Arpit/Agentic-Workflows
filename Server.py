import os
import logging
import base64
from typing import Dict, Any, Optional

import requests
import httpx
from fastmcp import FastMCP
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding

# ---------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
logger = logging.getLogger("indigo-mcp")

# ---------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------

mcp = FastMCP(
    name="IndiGo Unified Flight Services",
    stateless_http=True
)

# ---------------------------------------------------------------------
# Encryption Helper
# ---------------------------------------------------------------------

PUBLIC_KEY_PEM = """
-----BEGIN PUBLIC KEY-----
MIICIjANBgkqhkiG9w0BAQEFAAOCAg8AMIICCgKCAgEAyuc1oY3hXeeuiFb/9prBVG0m
C1ZcoK7RBin8izPXgiolPPM//0eIlTBf9bUhlVlU4dzPOiEVgedMUvnWzokEvT9tqo8U
1vk6WnMVMbo3OfVcTDKAIq782OJLNN6U0RCrQq4RQdb0dE5WQOxJ7lQnanbEP1uZO7Ex
kD2YE8n0CVTArnRa8u2k4wC9r4CjzDopBKfPYL5GtZVlOxiJYlysHgfRLosnmBsqfL8e
BEXmkICVqaZGa3yRyyQAWfNngGCdytDe1XR/buCjfz4Jj8Y5WKNpZ7OijqyRKnyysW5r
8/G+WV5RPEb06xsbA8iZOwqokQqDvl9Ml6u2Pyz9X/7thU/+RFUJPZO/seEC3tXVr8uO
XoB9Mu/eOIRez3gkzBEJGQXLdIef4S0hBUIPus9OhntMer2OcXTHIryvl+7Lvcqq45fl
A79NpK2e1chOcxBS5/lVMAc6xBjdFi+0WHqhm72he315w0xQp6Mua5bHrKAQvi+Tzw15
TjXcY9mZha/46JVgVX6/PsGyakSCK6F1YBeSSMYLsP4Ej8cH23LOtqkQlbqRKAX2tnEo
/7juHCtx7E9k3xHqB1dKR21qkf3Wq+qLERAtoZK40HcBb25CbKU21StYVI2pwRWCSTUP
GWG/Mtc1dShEX40J3HKVW2XwghjlyCY110G0K8dFAOvSNaUCAwEAAQ==
-----END PUBLIC KEY-----
"""

def encrypt(value: str) -> str:
    key = serialization.load_pem_public_key(PUBLIC_KEY_PEM.encode())
    encrypted = key.encrypt(
        value.encode(),
        padding.OAEP(
            mgf=padding.MGF1(hashes.SHA1()),
            algorithm=hashes.SHA1(),
            label=None,
        )
    )
    return base64.b64encode(encrypted).decode()

# ---------------------------------------------------------------------
# 1. Generate Token
# ---------------------------------------------------------------------

TOKEN_API_URL = "https://dotrezapi45-nonprod-3scale-apicast-production.apps.ocpnonprodcl01.goindigo.in/api/nsk/v2/token"
TOKEN_USER_KEY = os.getenv("TOKEN_USER_KEY", "b606c5f2277c7278d0be64a600635a21")

@mcp.tool(name="Generate_Token")
def generate_token() -> Dict[str, Any]:
    response = requests.post(
        TOKEN_API_URL,
        headers={
            "Content-Type": "application/json",
            "user_key": TOKEN_USER_KEY
        },
        json={},
        timeout=15
    )
    response.raise_for_status()
    return response.json()

# ---------------------------------------------------------------------
# 2. Eligibility
# ---------------------------------------------------------------------

ELIGIBILITY_API_URL = "https://api-uat-skyplus.goindigo.in/flightupgrade/v1/upgradestretch/eligibility"
ELIGIBILITY_USER_KEY = "2945e931b5e99bceed811fd202713432"
ELIGIBILITY_TIMEOUT_SEC = 15

# Alias for compatibility with the corrected function
encrypt_with_public_key = encrypt

@mcp.tool(
    name="Eligibility",
    description="Retrieve  Eligibility for a booking using Indigo APIs. Parameters: RecordLocator (required), LastName (required). Output: full eligibility JSON or error."
)
def Eligibility(RecordLocator: str, LastName: str, token: str) -> Dict[str, Any]:
    """
   Flow:
    1. Use the provided token.
    2. Call Retrieve endpoint with required body and LastName.
    3. Return retrieve JSON response or error.
    
    Args:
        RecordLocator: The booking record locator (required)
        LastName: The passenger's last name (required)
        token: The authorization token (required)
    """
    # Build input data from individual parameters
    input_data = {
        "RecordLocator": RecordLocator,
        "LastName": LastName,
    }
    
    # Encrypt all values for query params
    params = {k: encrypt_with_public_key(v) for k, v in input_data.items() if v is not None}

    # Step 1: Used the Generated_Token from the tool generate_token
    response =requests.get(RETRIEVE_API),
    
    # Step 2: Call eligibility endpoint
    headers = {
        "Authorization": token,
        "user_key": ELIGIBILITY_USER_KEY,
        "Content-Type": "application/json",
    }
    try:
        response = requests.get(
            ELIGIBILITY_API_URL,
            headers=headers,
            params=params,
            timeout=ELIGIBILITY_TIMEOUT_SEC,
        )
        response.raise_for_status()
        final_response = {
            "retrieve": response.json(),
            "token_used": token,
        }
        return final_response
    except requests.HTTPError as http_err:
        try:
            detail = response.json()
        except Exception:
            detail = response.text
        return {"status": response.status_code, "error": str(http_err), "response": detail}
    except Exception as e:
        return {"status": 500, "error": str(e)}

# ---------------------------------------------------------------------
# 3. Availability
# ---------------------------------------------------------------------

RETRIEVE_API = "https://api-uat-skyplus.goindigo.in/flightupgrade/v1/upgradestretch/retrieve"

@mcp.tool(name="Availability")
def availability(token: str) -> Dict[str, Any]:
    response = requests.get(
        RETRIEVE_API,
        headers={
            "Authorization": token,
            "user_key": ELIGIBILITY_USER_KEY
        },
        timeout=15
    )
    response.raise_for_status()
    result = response.json()
    found_key = False
    use_key = ""
    if("data" in result and result["data"] is not None and "journeys" in result["data"] and result["data"]["journeys"] is not None and len(result["data"]["journeys"]) > 0):
        for journey in result["data"]["journeys"]:
            found_key = False
            use_key = ""
            if("segments" in journey and journey["segments"] is not None and len(journey["segments"]) > 0):
                for segment in journey["segments"]:
                    if("classModifyKey" in segment and segment["classModifyKey"] is not None):
                        journey["classModifyKey"] = segment["classModifyKey"]
                        found_key = True
                        journey["useKey"] = "classModifyKey"
            if(found_key):
                continue
            if("fareOptions" in journey and journey["fareOptions"] is not None and len(journey["fareOptions"]) > 0):
                for fareOption in journey["fareOptions"]:
                    if("fareAvailabilityKey" in fareOption and fareOption["fareAvailabilityKey"] is not None):
                        journey["fareAvailabilityKey"] = fareOption["fareAvailabilityKey"]
                        journey["useKey"] = "fareAvailabilityKey"
                        found_key = True
                        break
    return result

# ---------------------------------------------------------------------
# 4. Dynamic Price
# ---------------------------------------------------------------------

DYNAMIC_PRICE_API = "https://ancillaryengine-nonprod-3scale-apicast-production.apps.ocpnonprodcl01.goindigo.in/stretch/recommendation"
STRETCH_USER_KEY = "a7d511cec49d91aa4978b1937cbd4451"

@mcp.tool(name="Dynamic_Price")
def dynamic_price(sector: str, authorization_token: str) -> Dict[str, Any]:
    response = requests.post(
        DYNAMIC_PRICE_API,
        headers={
            "authorization": authorization_token,
            "user_key": STRETCH_USER_KEY,
            "Content-Type": "application/json"
        },
        json={"sector": sector},
        timeout=15
    )
    response.raise_for_status()
    return response.json()

# ---------------------------------------------------------------------
# Flight Upgrade Tool
# ---------------------------------------------------------------------

UPGRADE_API_URL = r"https://api-uat-skyplus.goindigo.in/flightupgrade/v1/upgradestretch/upgrade"

@mcp.tool(
    name="upgradeStretchBooking",
    description="Upgrade flight journeys using the Indigo flight upgrade API. Parameters: journeyKey (required), classModifyKey (required).and Use the provided token  Output: JSON response with upgrade details."
)
def upgradeStretchBooking(journeyKey: str, classModifyKey: Optional[str], fareAvailabilityKey: Optional[str], token: str) -> Dict[str, Any]:
    """
    Flow:
    1. Use the provided token.
    2. Call upgrade endpoint with required headers and journey data.
    3. Return upgrade JSON response or error.
    
    Args:
        journeyKey: The journey key identifier (required)
        classModifyKey: The class modification key (required)
        token: The authorization token (required)
    """
    
    payload = {}
    print(journeyKey, classModifyKey, fareAvailabilityKey)
    # Step 2: Build payload from individual parameters
    if(classModifyKey is not None and classModifyKey != ""):
        payload = {
            "journeysToUpgrade": [
                {
                    "journeyKey": journeyKey,
                    "classModifyKey": classModifyKey
                }
            ]
        }
    elif(fareAvailabilityKey is not None and fareAvailabilityKey != ""):
        payload = {
            "journeysToUpgrade": [
                {
                    "journeyKey": journeyKey,
                    "fareKey": fareAvailabilityKey
                }
            ]
        }
    else:
        return {
            "status": 400,
            "error": "Either classModifyKey or fareAvailabilityKey must be provided."
        }
    print(payload)
    # Step 3: Call upgrade endpoint
    headers = {
        "Authorization": token,
        "user_key": ELIGIBILITY_USER_KEY,
        "Content-Type": "application/json",
        "Cookie": "0e301b3d9667a680d70f059c3902e4b1=d3c15babc1f494e3c474d6c32a397e37; 6b3f2552215b6b1885935a0b015c2546=e37873bf04697e711eaa77eecb9cec0b"
    }
    
    try:
        logger.info(f"Calling upgrade API: {UPGRADE_API_URL}")
        logger.info(f"Headers: {headers}")
        logger.info(f"Payload: {payload}")
        
        response = requests.post(
            UPGRADE_API_URL,
            headers=headers,
            json=payload,
            timeout=ELIGIBILITY_TIMEOUT_SEC,
        )
        print(response)
        
        logger.info(f"Response status: {response.status_code}")
        logger.info(f"Response headers: {response.headers}")
        
        try:
            response.raise_for_status()
            result = response.json()
            logger.info("Flight upgrade processed successfully")
            
            final_response = {
                "upgrade": result,
                "token": token,
            }
            return final_response
            
        except requests.HTTPError as http_err:
            try:
                detail = response.json()
                # Check if the customer is already upgraded
                return {
                    "status": "already_upgraded",
                    "message": "You are already upgraded to Stretch seat. No further upgrade is needed.",
                    "customer_message": "Your seat has already been upgraded. Enjoy your enhanced travel experience!",
                    "details": detail
                }
            except Exception:
                detail = response.text
                # Check text response for upgrade status
                return {
                    "status": "already_upgraded", 
                    "message": "You are already upgraded to Stretch seat. No further upgrade is needed.",
                    "customer_message": "Your seat has already been upgraded. Enjoy your enhanced travel experience!",
                    "details": detail
                }
            
            # logger.error(f"HTTP error: {http_err} | Details: {detail}")
            # return {
            #     "status": response.status_code, 
            #     "error": str(http_err), 
            #     "response": detail,
            # }
            
    except requests.Timeout:
        logger.error(f"Request timed out after {ELIGIBILITY_TIMEOUT_SEC}s")
        return {
            "status": 500, 
            "error": f"Request timeout after {ELIGIBILITY_TIMEOUT_SEC}s"
        }
    except Exception as e:
        logger.error(f"Upgrade API call failed: {e}")
        return {"status": 500, "error": f"API call failed: {str(e)}"}

# ---------------------------------------------------------------------
# 5. Get Entire Seats
# --------------------------------------------------------------------
@mcp.tool(name="GetEntireSeats")
async def get_entire_seats(authorization: str) -> Dict[str, Any]:
    if not authorization.startswith("Bearer "):
        authorization = f"Bearer {authorization}"

    async with httpx.AsyncClient() as client:
        response = await client.get(
            "https://api-qa-seat-selection-skyplus6e.goindigo.in/v1/seat/getentireseats",
            headers={
                "Authorization": authorization,
                "user_key": "9ad8345ab99a9874003b26b2fa5d3bea"
            },
            timeout=30
        )
        response.raise_for_status()
        result = response.json()
        if("data" in result and result["data"] is not None and "seatMaps" in result["data"] and result["data"]["seatMaps"] is not None and len(result["data"]["seatMaps"]) > 0):
            for seatMap in result["data"]["seatMaps"]:

                
                if("seatMap" in seatMap and seatMap["seatMap"] is not None and "decks" in seatMap["seatMap"] and "1" in seatMap["seatMap"]["decks"] and seatMap["seatMap"]["decks"]["1"] is not None and "compartments" in seatMap["seatMap"]["decks"]["1"] and seatMap["seatMap"]["decks"]["1"]["compartments"] is not None):
                        compartment = seatMap["seatMap"]["decks"]["1"]["compartments"]
                        if("C" in compartment and compartment["C"] is not None and "units" in compartment["C"] and compartment["C"]["units"] is not None and len(compartment["C"]["units"]) > 0):
                            if("availableUnits" in compartment["C"] and compartment["C"]["availableUnits"] is not None and compartment["C"]["availableUnits"] <= 0):
                                return result
                            for unit in compartment["C"]["units"]:
                                if("availability" in unit and unit["availability"] is not None and unit["availability"] == 5):
                                    return result
                    
        return result

# ---------------------------------------------------------------------
# 6. CDP Token Generation (FirstHive)
# ---------------------------------------------------------------------

@mcp.tool(name="CDP_Token_Generation")
def cdp_token_generation(
    username: str = "InOther",
    password: str = "bgcHisrO",
    role: str = "reader"
) -> Dict[str, Any]:
    response = requests.post(
        "https://ind1-de.firsthive.com/GentokenAPI_ID",
        json={
            "username": username,
            "password": password,
            "role": role
        },
        timeout=15
    )
    response.raise_for_status()
    return response.json()

# ---------------------------------------------------------------------
# 7. Retrieve Customer Details
# ---------------------------------------------------------------------

@mcp.tool(name="RetreiveCustomerDetails")
async def retrieve_customer_details(email: str, mobile: str, fy: str = "2025",) -> Dict[str, Any]:
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://ind1-de.firsthive.com/customerDetailAPI",
            json={"email": email, "mobile": mobile, "fy": fy},
            timeout=30
        )
        response.raise_for_status()
        return response.json()

# ---------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run(
        transport="streamable-http",
        host="127.0.0.1",
        port=8001,
        path="/mcp"
    )
