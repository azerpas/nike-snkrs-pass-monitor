import json, random
import os
from typing import Final, Optional
from botocore.vendored import requests
import boto3

WARNING_PNG: Final = "https://upload.wikimedia.org/wikipedia/commons/thumb/1/17/Warning.svg/832px-Warning.svg.png"

def lambda_handler(event, context):
    # Proxies are stored inside environment variables as we use proxies with auth
    proxy = { 
        "http": os.environ["PROXY"],
        "https": os.environ["PROXY"]
    }

    # Initiate requests session
    s = requests.session()
    s.proxies.update(proxy)
    
    headers = {
        'authority': 'api.nike.com',
        'cache-control': 'max-age=0',
        'upgrade-insecure-requests': '1',
        'user-agent': getUserAgent(),
        'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9',
        'sec-fetch-site': 'none',
        'sec-fetch-mode': 'navigate',
        'sec-fetch-user': '?1',
        'sec-fetch-dest': 'document',
        'accept-language': 'en,en-US;q=0.9,fr;q=0.8',
    }
    
    # Params are fetch from Nike SNKRS app
    params = (
        ('format', 'v4'),
        ('upcoming', 'true' if os.environ["UPCOMING"] else 'false'),
        ('anchor', str(os.environ["ANCHOR"])),
        ('language', os.environ["LANG"]),
        ('marketplace', os.environ["MARKETPLACE"]),
        ('includeContentThreads', 'false'),
        ('exclusiveAccess', 'true,false' if os.environ["EXCLUSIVE_ACCESS"] else 'false'),
        ('sort', 'productInfo.merchProduct.commerceStartDateAsc'),
    )
    
    response = s.get(os.environ["URL"], headers=headers, params=params, proxies=proxy, verify=False)
    
    print(response.text)
    
    # Nike has identified us a robot or modified its API
    if response.status_code != 200:
        toDiscord("Error", str(response.status_code) + str(response.text), WARNING_PNG, getAdminDiscordUser() + " Please check the error")
        return {
            'statusCode': response.status_code,
            'body': json.dumps('Not response 200: '+str(response.status_code) + "\n")
        }
        
    client = boto3.client('dynamodb')

    # Init the previousPass DynamoDB Table to null and only fetch it if we find a SNKRS PASS inside the new releases
    previousPass = None
    newStash = []
    
    # Loop through objects list
    if("objects" in response.json()):
        for obj in response.json()["objects"]:
            s = "SNKRS PASS".lower()

            # Get some properties from snkrs object
            id = obj["id"]
            title = obj["publishedContent"]["properties"]["title"].lower()
            if "tags" in obj["publishedContent"]["properties"]["custom"]:
                if len(obj["publishedContent"]["properties"]["custom"]["tags"]) > 0:
                    tag = obj["publishedContent"]["properties"]["custom"]["tags"][0].lower()
                else: 
                    tag = ""
            else: 
                tag = ""
            description = obj["publishedContent"]["properties"]["seo"]["description"].lower()

            # "SNKRS PASS" contained in object details
            if( (s in title) or (s in tag) or (s in description) ):
                new = True

                # previousPass hasn't been initialized before
                if previousPass == None:
                    previousPass = client.scan(
                        TableName="SnkrsPass",
                        Select="SPECIFIC_ATTRIBUTES",
                        AttributesToGet=["id"]
                    )

                # Iterate through previous found snkrs pass
                for i in previousPass["Items"]:
                    if( id == i["id"]["S"] ): # if already in database new = False
                        new = False
                
                if new:
                    newStash.append(obj)
                    toDiscord(obj["publishedContent"]["properties"]["title"], obj["publishedContent"]["properties"]["seo"]["description"], obj["publishedContent"]["properties"]["coverCard"]["properties"]["squarishURL"])

        if len(newStash) == 0:
            return {
                'statusCode': 200,
                'body': "No new stash or pass"
            }
            
        # Add the new Pass to our DB
        itemsToTable = []
        for i in newStash:
            print(i["id"])
            print(i["publishedContent"]["properties"]["title"])
            print(i["publishedContent"]["properties"]["seo"]["description"])
            itemsToTable.append({"PutRequest": {"Item": dict_to_item(i)} })
        #https://docs.aws.amazon.com/amazondynamodb/latest/APIReference/API_BatchWriteItem.html#API_BatchWriteItem_Examples
        response = client.batch_write_item(
            RequestItems={
                'SnkrsPass': itemsToTable
            }
        )

    # Response doesn't contain objects properties, something changed in Nike Backend or the request is unsuccessfull
    else:
        toDiscord("ERROR", str(response.text), WARNING_PNG, getAdminDiscordUser() + " Please check the error")
        return {
            'statusCode': response.status_code,
            'body': json.dumps('No objects in response '+str(response.status_code) + "\n"+ str(response.text))
        }

    print(response)
    return {
        'statusCode': response.status_code,
        'body': json.dumps('Response from client: '+str(response.status_code) + "\n"),
        'code': response.status_code
    }

#https://gist.github.com/JamieCressey/a3a75a397db092d7a70bbe876a6fb817
def dict_to_item(raw):
    if isinstance(raw, dict):
        return {
            'M': {
                key: dict_to_item(value) for key, value in raw.items()
            }
        }
    elif isinstance(raw, list):
        return {
            'L': [dict_to_item(value) for value in raw]
        }
    elif isinstance(raw, (str)):
        return {'S': raw}
    elif isinstance(raw, (int, float)):
        return {'N': str(raw)}
    elif isinstance(raw, bool):
        return {'BOOL': raw}
    elif isinstance(raw, bytes):
        return {'B': raw}
    elif raw is None:
        return {'NULL': True}
        
def toDiscord(title: str, description: str, thumbnail: str, content: Optional[str] = None):
    """Post message to Discord Webhook

    Args:
        title (str): Title of the embedded Discord Webhook
        description (str): Description of the embedded Discord Webhook
        thumbnail (str): Thumbnail of the embedded Discord Webhook
        content (Optional[str], optional): Content of the Discord Webhook message. Defaults to None.
    """
    message = {
      "content": content,
      "embeds": [
        {
          "title": "SNKRS PASS",
          "color": 7506394,
          "fields": [
            {
              "name": "Title",
              "value": title
            },
            {
              "name": "Description",
              "value": description
            },
            {
              "name": "OPEN YOUR SNKRS APP",
              "value": "HERE"
            }
          ],
          "thumbnail": {
            "url": thumbnail
          }
        }
      ],
      "username": "AZER-PASS"
    }
    url = os.environ["WEBHOOK"]
    requests.post(url, headers={"Content-Type": "application/json"}, data=json.dumps(message))

def getUserAgent() -> str:
    """Get a random UA from our list of user agents

    Returns:
        str: user-agent
    """
    file = open("ua.txt")
    lines = file.readlines()
    return random.choice(lines).replace("\n","")

def getAdminDiscordUser() -> str:
    """Get the Admin ID of the Discord Server

    Returns:
        str: Admin ID
    """
    if "USER" in os.environ:
        return "<@" + os.environ["USER"] + ">"
    else:
        return ""