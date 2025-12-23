import os
from typing import Dict, Any, Optional
from azure.identity import AzureCliCredential
from azure.ai.agents import AgentsClient
from azure.core.exceptions import HttpResponseError
import json
import requests

deployment_name = "gpt-4o-mini"  # deployment/model name
endpoint = "https://6eopenai-aifoundry-np-ea.services.ai.azure.com/api/projects/project-aifoundry-np-ea-webnmob"

agent_name = "Airline Upgrade Orchestrator Agent1"
instructions = """
You are an Airline Upgrade Orchestrator Agent
Goal: Given encrypted PNR and LastName, determine upgrade eligibility and availability, fetch prices and seats, and construct the best upgrade bundle(s) per sector.
Input:Record Locator (PNR), Passenger Last Name
Steps to Follow:
Retrieve Upgrade Eligibility Details.
"isPlanB": false,
      "isSlt": false,
      "isGroupBooking": false
All of these are false -> PNR is eligible for an upgrade
journey-Level Upgrade check 
data.journeys.
 "upgradeEligiblityDetails": {
          "isFlown": false,
          "isRestrictedByTime": false,
          "isCheckedIn": false,
          "isConnecting": false,
          "isRestrictedByProductClass": false
          }
All of these are false -> journey is eligible for an upgrade

Now call the MCP Tool to: Availablity.
"isSegmentLevelUpgradeAllowed": true,
If it is true -> Flat fee upgrade window -> segment level upgrade 
If it is false -> fare difference upgrade window -> journey level upgrade
Flat Fee - Segment Level Upgrade 
"Classmodifykey"
if this is not null -> segment level upgrade is available
if this is null -> segment level upgrade is not available directly move to fare difference upgrade check
Fare Difference - Journey Level Upgrade
"Fareoption": []
this is empty -> fare difference upgrade is not available
this is not empty -> fare difference upgrade is available
store the faireAvailability details for further processing

MCP call while only segment level upgrade is availble:Dynamic Price.
pass the segment details to get the price
if price is returned -> use it  
if price is NOT returned -> apply fallback price ₹10,000
now call the MCP Tool to: GetEntireSeat.
filter seats using all of the following:
compartment = Y (Stretch / Business)
assignable = true
availability ≥ 5 
seat is eligible for sell
now select the best available seat — do not ask the customer. and assign seat to passenger.
now call the MCP Tool to: CDP Token Generation.
now call the MCP Tool to: RetreiveCustomerDetails.
Use CDP data only for:
Personalization 
Ranking
Tie-breaking between eligible sectors       
CDP data must never override:
now sugegst only one sector
Include sector + seat + price   
Final Output:
Based on the above steps, suggest upgrade bundle(s) 
and Handle both conditions: is sector-level and journey-level upgrades.
and Suggest best bundle(s) 
"""

print(f"Connecting to Azure AI Agents at: {endpoint}")
client = AgentsClient(endpoint=endpoint, credential=AzureCliCredential())
print(f" Connected to Azure AI Agents using Azure CLI credentials.")

def get_agent_by_name(client: AgentsClient, name: str):
    """
    Returns the first agent whose name matches `name` (case-sensitive).
    If multiple agents share the same name, returns the first one encountered.
    """
    try:
        for agent in client.list_agents():
            current_name = getattr(agent, "name", None) or (agent.get("name") if isinstance(agent, dict) else None)
            if current_name == name:
                return agent
        return None
    except HttpResponseError as e:
        print(f"Failed to list agents: {e}")
        return None

def get_or_create_agent(client: AgentsClient, name: str, model: str, instructions: str):
    """
    Idempotent helper:
    - If an agent with `name` exists, return it.
    - Otherwise, create the agent and return the new one.
    """
    existing = get_agent_by_name(client, name)
    if existing:
        existing_id = getattr(existing, "id", None) or (existing.get("id") if isinstance(existing, dict) else None)
        print(f" Agent already exists. Reusing agent '{name}' (ID: {existing_id}).")
        return existing
    try:
        agent = client.create_agent(
            model=model,
            name=name,
            instructions=instructions,
        )
        print(f"Agent created with ID: {agent.id}")
        return agent
    except HttpResponseError as e:
        print(f"Error creating agent: {e}")
        raise

try:
    agent = get_or_create_agent(
        client=client,
        name=agent_name,
        model=deployment_name,
        instructions=instructions,
    )
    print(f"Agent ready. ID: {agent.id}")
except Exception as e:
    print(f" Error during agent get/create: {e}")

# =====================================================
# MCP CONFIG
# =====================================================

MCP_URL = "http://127.0.0.1:8001/mcp"

# =====================================================
# MCP TOOL EXECUTOR
# =====================================================

def execute_mcp_function(mcp_url: str, function_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    function_to_tool_map = {
        "generate_token": "Generate_Token",
        "eligibility": "Eligibility",
        "availability": "Availability",
        "dynamic_price": "Dynamic_Price",
        "get_entire_seats": "GetEntireSeats",
        "cdp_token": "CDP_Token_Generation",
        "cdp_profile": "RetreiveCustomerDetails",
        "upgrade_booking": "upgradeStretchBooking"
    }

    tool_name = function_to_tool_map.get(function_name)
    if not tool_name:
        return {"status": "error", "message": f"Unknown MCP function: {function_name}"}

    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": tool_name,
            "arguments": arguments or {}
        }
    }

    try:
        response = requests.post(
            mcp_url,
            json=payload,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream"
            },
            timeout=30
        )

        if not response.ok:
            return {"status": "error", "message": f"HTTP {response.status_code}", "raw": response.text}

        # Handle SSE
        if "text/event-stream" in response.headers.get("content-type", ""):
            for line in response.text.splitlines():
                if line.startswith("data:"):
                    data = json.loads(line.replace("data:", "").strip())
                    return {"status": "success", "data": data.get("result")}
        else:
            result = response.json()
            return {"status": "success", "data": result.get("result", result)}

    except Exception as e:
        return {"status": "error", "message": str(e)}

# =====================================================
# CDP PREFERENCE EXTRACTION
# =====================================================

def extract_seat_preferences(cdp_profile: Dict[str, Any]) -> Dict[str, Any]:
    preferences = {}
    try:
        data = cdp_profile.get("structuredContent",{}).get("data", {})
        if(data == {}):
            data = {
                "age": 0,
                "agentcorP_MOBILEAPP": 0,
                "agentcorP_WEB": 0,
                "aisle": 0,
                "annualtrips": 2,
                "avgweightdom": "5.00",
                "avgweightint": "0.00",
                "b2C_MOBILEAPP": 0,
                "b2C_OTA": 0,
                "b2C_WEB": 0,
                "beaches": 0,
                "bookconnection": 0,
                "bundleproducts": 0,
                "business": 0,
                "cancellatioN_COUNT": 0,
                "changE_COUNT": 0,
                "child": 0,
                "companion": 0,
                "corporate": 0,
                "dayflight": 0,
                "defense": 0,
                "departurE_FY": 2023,
                "dependenttravel": 0,
                "detractor": 0,
                "doctoR_NURSE": 0,
                "domestic": 2,
                "earlyplanner": 2,
                "email": "mananbhatia02@gmail.com",
                "eveningflight": 1,
                "excessbaggage": 0,
                "family": 0,
                "familY_FARE": 0,
                "female": 0,
                "festivaltraveler": 0,
                "ffwd": 0,
                "firstdateofdeparture": "Wed, 24 Aug 2022 05:05:00 GMT",
                "firstname": "MANAN",
                "firsT_USR_UNIQUE_ID": "FA-C673CBC2B0314FA5-984974775",
                "flewbeforE2FY": "Y",
                "flexi": 0,
                "fliesconnection": 0,
                "flyingafteR2FY": "N",
                "foreigncurrency": 0,
                "group": 0,
                "guid": "654e0c6a-40fe-4eef-a86f-04e53f608639",
                "highspenderhighfreq": "N",
                "highspenderlowfreq": "N",
                "hotelcustomer": "N",
                "infant": 0,
                "international": 0,
                "lastchannel": "Other_Agents_TMC_B2B_etc",
                "lastminuteflyer": 0,
                "lastname": "BHATIA",
                "leisure": 2,
                "lowspenderhighfreq": "N",
                "lowspenderlowfreq": "Y",
                "male": 1,
                "metrO_METRO": 0,
                "metrO_NONMETRO": 1,
                "middle": 3,
                "mobile": "9718822702",
                "morningflight": 1,
                "mountains": 0,
                "multicity": 0,
                "newcustomer": "Y",
                "nobaggagesegments": 0,
                "nofilteR_COLLAB": "N",
                "nonmetrO_METRO": 1,
                "nonmetrO_NONMETRO": 0,
                "noN_VEG_MEAL": 0,
                "onetimeflier": 1,
                "oneway": 0,
                "otherbooked": 0,
                "others": 0,
                "otheR_AGENTS_TMC_B2B_ETC": 1,
                "otheR_FARE_TYPES": 0,
                "passive": 0,
                "plains": 2,
                "preferreddestination": "DEL",
                "preferredorigin": "DEL",
                "promo": 2,
                "promocode": 0,
                "promoter": 0,
                "redeyeflight": 0,
                "repeatcustomer": "N",
                "return": 0,
                "roundtrip": 2,
                "roundtripS_DIFFPNR": 0,
                "saver": 0,
                "secondlastchannel": "",
                "selfbooked": 1,
                "skai": 0,
                "sme": 0,
                "solo": 1,
                "spotifY_COLLAB": "N",
                "sR_CITIZEN": 0,
                "stretch": 0,
                "student": 0,
                "supeR6E": 0,
                "totalnoshowsegments": 0,
                "totalpnr": 1,
                "totalsegments": 2,
                "totalspend": "11066.00",
                "totaltrips": 2,
                "totaL_INFLIGHT_SPEND": "0.00",
                "tripS_INSURED": 0,
                "unaccompanieD_MINOR": 0,
                "uniquedestinations": 2,
                "uniqueorigins": 2,
                "veG_MEAL": 0,
                "weekdaytravel": 2,
                "weekendtravel": 0,
                "wheelchair": 0,
                "window": 2,
                "xl": 0,
                "msg": None
            }
        seat_preference = None
        level_of_preference = 0
        for k,v in data.items():
            if "aisle" in k.lower() and v > 0 and level_of_preference < v:                
                seat_preference = "aisle"
                level_of_preference = v
            if "window" in k.lower() and v > 0 and level_of_preference < v:
                seat_preference = "window"
                level_of_preference = v
            if "middle" in k.lower() and v > 0 and level_of_preference < v:
                seat_preference = "middle"
                level_of_preference = v
            
        return seat_preference
    except Exception:
        pass
    return preferences

# =====================================================
# AUTO SEAT SELECTION (NO USER INPUT)
# =====================================================

def auto_select_seat(seats_resp: Dict[str, Any], seat_preference: Optional[str]) -> Optional[Dict[str, Any]]:
    try:
        data = seats_resp.get("data", {}).get("structuredContent",{}).get("data", {})
        seat_maps = data.get("seatMaps", [])
        passengers = data.get("passengers", [])
        pax_count = len(passengers)
        seats=[]
        for sm in seat_maps:
            compartments = sm["seatMap"]["decks"]["1"]["compartments"]
            if "C" not in compartments:
                continue
            
            for seat in compartments["C"].get("units", []):
                if not seat.get("assignable"):
                    continue
                selected_seat = None
                if seat_preference is not None:
                    for prop in seat.get("properties", []):
                        if prop.get("code").lower() == seat_preference and prop.get("value").lower() == "true":
                            selected_seat = seat
                            break 
                    if(selected_seat is None):
                        continue
                            
                else:
                    selected_seat = seat
                    
                    
                if(len(seats) < pax_count): # and seat.get("availability",0) >=5):
                    selected_seat["passengerKey"]=passengers[len(seats)].get("passengerKey","")
                    seats.append(selected_seat)
                else:
                    return seats
            if(len(seats) < pax_count):
                for seat in compartments["C"].get("units", []):
                    if not seat.get("assignable"):
                        continue
                    taken = [taken_seat for taken_seat in seats if seat.get("unitKey","") == taken_seat.get("unitKey","")]
                    if(len(taken) >0):
                        continue
                    
                    if(len(seats) < pax_count): # and seat.get("availability",0) >=5):
                        seat["passengerKey"]=passengers[len(seats)].get("passengerKey","")
                        seats.append(seat)
    

    except Exception as ex:
        return None

    return seats

# =====================================================
# MAIN POP SECTOR-LEVEL UPGRADE AGENT
# =====================================================

def pop_sector_upgrade_agent(
    pnr: str,
    last_name: str,
    email: Optional[str] = None,
    mobile: Optional[str] = None
) -> Dict[str, Any]:

    # --------------------------------------------------
    # Step 1: Generate Token
    # --------------------------------------------------
    token_resp = execute_mcp_function(MCP_URL, "generate_token", {})
    if token_resp["status"] != "success":
        return {"suggestion": "NO", "reason": "Token generation failed"}
    data = token_resp.get("data", {}).get("structuredContent", {})
    token = data["data"].get("token")
    if not token:
        return {"suggestion": "NO", "reason": "Invalid token"}

    # --------------------------------------------------
    # Step 2: Eligibility (PNR Level)
    # --------------------------------------------------
    eligibility = execute_mcp_function(
        MCP_URL,
        "eligibility",
        {"RecordLocator": pnr, "LastName": last_name, "token": token}
    )
    data = eligibility.get("data", {}).get("structuredContent", {})
    print(data)
    flags = data.get("retrieve", {}).get("upgradeEligiblityDetails", {})
    

    if flags.get("isPlanB") or flags.get("isSlt") or flags.get("isGroupBooking"):
        return {"suggestion": "NO", "reason": "PNR not eligible"}

    # --------------------------------------------------
    # Step 3: Availability (Retrieve)
    # --------------------------------------------------
    availability = execute_mcp_function(MCP_URL, "availability", {"token": token})
    journeys = availability["data"].get("structuredContent", {}).get("data", {}).get("journeys", [])
    upgradable_journeys = []
    for journey in journeys:
        useKey = journey.get("useKey","")
        if(useKey and useKey == "fareAvailabilityKey"):
            upgradable_journeys.append(journey)
            continue
        upgradable_segments = []
        for segment in journey.get("segments", []):
            key = segment.get("classModifyKey", "")
            if key and len(key) > 0:
                upgradable_segments.append(segment)
                break
        if(len(upgradable_segments) > 0):
            journey["segments"] = upgradable_segments
            upgradable_journeys.append(journey)

    if len(upgradable_journeys) == 0:
        return {"suggestion": "NO", "reason": "No sector-level upgrade available"}

     # --------------------------------------------------
    # Step 5: CDP Preferences (AUTO)
    # --------------------------------------------------
    seat_preference = None
    if email and mobile:
        cdp_token = execute_mcp_function(MCP_URL, "cdp_token", {})
        if cdp_token["status"] == "success":
            profile = execute_mcp_function(
                MCP_URL,
                "cdp_profile",
                {"email": email, "mobile": mobile}
            )
            seat_preference = extract_seat_preferences(profile.get("data", {}))

    # --------------------------------------------------
    # Step 4: Dynamic Pricing
    # --------------------------------------------------
    results = []
    for journey in upgradable_journeys:
        d = journey.get("designator", {})
        origin, destination = None, None
        segements = journey.get("segments", [])
        if len(segements) > 0:
            origin = segements[0].get("designator", {}).get("origin")
            destination = segements[-1].get("designator", {}).get("destination")
        
        sector = f"{origin}-{destination}"
        fare_price = None
        if("fareAvailabilityKey" in journey and journey["fareAvailabilityKey"] is not None and len(journey["fareAvailabilityKey"]) > 0):
            fare_price = journey.get("fareOptions", [{}])[0].get("totals" , {}).get("fareTotal", None)
        journey.get("fareOptions", [])
        price_resp = execute_mcp_function(
            MCP_URL,
            "dynamic_price",
            {"sector": sector, "authorization_token": token}
        )

        price = price_resp.get("data", {}).get("price") or fare_price or 10000
        journey["upgradePrice"] = price

        # --------------------------------------------------
        # Step 6: Seat Map + Auto Selection
        # --------------------------------------------------
        seats_resp = execute_mcp_function(
            MCP_URL,
            "get_entire_seats",
            {"authorization": token}
        )

        seats = auto_select_seat(seats_resp, seat_preference)
        if not seats or len(seats) < 0:
            return {"suggestion": "NO", "reason": "No eligible seats found"}

        # --------------------------------------------------
        # Step 7: Final POP Bundle
        # --------------------------------------------------
        results.append( {
            "suggestion": "YES",
            "bundle": {
                "type": "Best_SECTOR_LEVEL_Available_Stretch_Bundle",
                "sector": sector,
                "journey_details": journey,
                "seat": seats,
                "price": price,
                "autoSelected": True
            }
        })
    mx=0
    result=[]
    for res in results:
        if(res["bundle"]["price"] > mx):
            mx=res["bundle"]["price"]
            result=[res]
    return {"results": result}
    

# =====================================================
# EXAMPLE RUN
# =====================================================

if __name__ == "__main__":
    result = pop_sector_upgrade_agent(
        pnr="TPUW5F",
        last_name="Tripathi",
        email="tripathikiot@gmail.com",
        mobile="6387133369"
    )

    print(json.dumps(result))