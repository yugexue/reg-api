# main.py
# registration gateway
# This script allows to 

#General imports
import os
from fastapi import FastAPI, Body, Path, Request
from fastapi import Depends, HTTPException, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
import asyncio
import json
from urllib.request import Request as URLlibRequest, urlopen as URLlibUrlopen
from urllib.error import URLError, HTTPError
import datetime as dt
import re
import shutil
import stat

#Setup FastAPI
app = FastAPI(title="Registration Gateway",description="""This API interface allows you to ingest at the same time metadata and related data assets. 

Auhtorized users can **POST a new STAC Item** into a Collection, linking assets uploaded into S3 stagein bucket associated to the Collection. The assets will be moved to the system long-term storage and the metadata updated and ingested into the sytstem clatalogue for long term data preservation.

The the **STAC Items** posted shall follow the following profile:

| Element | Type | Description |
| ---------------- | -------------------- | ----------- |
| type | string | **REQUIRED.** Must be set to `Feature`.|
| stac_version | string | **REQUIRED.** The STAC version. Recommended to be set to `1.0.0` |
| stac_extensions | \\[string] | **REQUIRED** A list of extension identifiers the Collection implements. Must contain at least the [File extension](https://stac-extensions.github.io/file/v2.1.0/schema.json) |
| id| string | **REQUIRED.** Item identifier. The ID should be unique within the Collection that contains the Item. The id metadata can contain only the [a-zA-Z0-9._-] characters and shall have maximum 100 characters. |
| geometry | GeoJSON Geometry Object or null | **REQUIRED.** Defines the full footprint of the asset represented by this item, formatted according to RFC 7946, [section 3.1](https://tools.ietf.org/html/rfc7946#section-3.1) if a geometry is provided or [section 3.2](https://tools.ietf.org/html/rfc7946#section-3.2) if *no* geometry is provided. |
| bbox | \\[number] | **REQUIRED if `geometry` is not `null`, prohibited if `geometry` is `null`.** Bounding Box of the asset represented by this Item, formatted according to [RFC 7946, section 5](https://tools.ietf.org/html/rfc7946#section-5).                                                                            |
| properties.start_datetime | string | **REQUIRED.** The first or start date and time for the resource, in UTC. It is formatted as `date-time` according to [RFC 3339, section 5.6](https://tools.ietf.org/html/rfc3339#section-5.6). |
| properties.end_datetime   | string | **REQUIRED.** The last or end date and time for the resource, in UTC. It is formatted as `date-time` according to [RFC 3339, section 5.6](https://tools.ietf.org/html/rfc3339#section-5.6).    |
| properties.datetime | string | The searchable date and time of the assets, which must be in UTC. If not specified or null, it will be set to `start_datetime`. |
| assets | Map<string, [Asset Object](https://github.com/radiantearth/stac-spec/blob/master/collection-spec/collection-spec.md#assets)>| **REQUIRED.** Dictionary of asset objects that can be downloaded, each with a unique key. Further constrains on asset values are below |
| assets[].href | string | **REQUIRED.** Each asset of the STAC Item containing an URI as `href` is ingored and will be posted into the Catalogue as-is. Each asset of the STAC Item containing a local path as `href` is transferred from the stagein area to the main storage area. It shall thus have: An `href` pointing to the relative path of the asset binary file or directory into the S3 stagein bucket associated to the Collection. An `href` filename containing only the [a-zA-Z0-9._-] characters (the rest of the filename path is ignored). The filename shall have maximum 100 characters. An `href` filename unique among all the STAC Item assets (two assets in the same STAC item cannot have the same filename, even if they have different relative paths)  |
| assets[].type | string | **REQUIRED.** [Media type](https://pystac.readthedocs.io/en/stable/api/media_type.html) of the asset. It is **strongly reommended** to use for raster Cloud-native formats such as **[COG](https://cogeo.org/)** or **[EOPF-Zarr](https://zarr.eopf.copernicus.eu/)** and for vectors formats such as **[FlatGeobuf](https://flatgeobuf.org/)**, **[GeoJSON](https://geojson.org/)** and **[GeoParquet](https://geoparquet.org/)**. See the [common media types](https://github.com/radiantearth/stac-spec/blob/master/best-practices.md#common-media-types-in-stac) for commonly used asset types. |      |
| assets[].roles | \\[string] | **REQUIRED.** The [semantic roles](#roles) of the asset, similar to the use of `rel` in links. It is **REQUIRED.** to have at least one 'data' or one 'documentation' asset per product. |
| assets[].file:checksum | string | It is **strongly recommended** to provide the file checksum. The hashes are self-identifying hashes as described in the [Multihash specification](https://github.com/multiformats/multihash), with only sha1, sha2-256 and sha2-512 supported and must be encoded as hexadecimal string with lowercase letters. |
| assets[].file:size | integer | **REQUIRED.** The file size, specified in bytes. If a local asset is specified, this is checked. |

""",version="0.0.2")

#Get current script execution path
CURPATH = os.path.dirname(os.path.realpath(__file__))
CFGPATH = os.path.realpath(os.path.join(CURPATH,"../cfg"))

#Use SQLite database to store AAI and other configuration information. Open this in read only mode
import sqlite3
con = sqlite3.connect('file:'+os.path.join(CFGPATH,"auth.db")+'?mode=ro',uri=True,check_same_thread=False)

#Use basic HTTP security for the endpoints (get username/password from the configuration DB)
from fastapi.security import HTTPBasic, HTTPBasicCredentials
import hashlib
security = HTTPBasic()
def get_current_username(credentials: HTTPBasicCredentials = Depends(security)):
  #Open connection to the db
  cur = con.cursor()
  #Query for the ID. If retreived, the user is logged in
  cur.execute("SELECT id FROM auth WHERE username = :username AND password_sha256 = :password_sha256;",{"username": credentials.username,"password_sha256": hashlib.sha256(credentials.password.encode("utf8")).hexdigest()})
  query_result = cur.fetchone()
  if query_result and len(query_result) > 0 and query_result[0] is not None:
    return query_result[0]
  else:
    raise HTTPException(
      status_code=status.HTTP_401_UNAUTHORIZED,
      detail="Incorrect username or password",
      headers={"WWW-Authenticate": "Basic"},
    )

#Check the authorization using the configuration DB
def check_user_collection_authorization(user_id: int, collection_name: str):
  #Open connection to the db
  cur = con.cursor()
  #Query for the collection id map to the user
  cur.execute("SELECT stagein_path, assets_path, stacs_path, datastore_url, cat_post_url, extra_auths FROM user_collection_write_map WHERE collection_name = :collection_name AND user_id= :user_id;",{"user_id": user_id,"collection_name": collection_name})
  query_result = cur.fetchall()
  cur.close()
  if query_result and len(query_result) > 0:
    return query_result[0]
  else:
    raise HTTPException(
      status_code=status.HTTP_401_UNAUTHORIZED,
      detail="User is not authorized to this collection",
      headers={"WWW-Authenticate": "Basic"},
    )


#Rewrite the validation error to make it look like a GeoJSON error
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
  return JSONResponse(status_code=422,content={'id':'unknown','failure_reason':str(exc)})

@app.post(
  "/collections/{collectionId}/items",
  tags=["Implemented transaction operations:"],
  summary="Register an Item or an ItemCollection",
  description="""This call performs a registration of a [STAC Item](https://github.com/radiantearth/stac-spec/blob/master/item-spec/item-spec.md) or [STAC ItemCollection](https://github.com/radiantearth/stac-api-spec/tree/release/v1.0.0/fragments/itemcollection) (a set of STAC Items) into the Catalogue.

To access it, you need to be registered as Data Provider and authorized to publish in the Catalogue collection (_{collectionId}_ in the API endpoint path).

The POST request body needs to contain the STAC Item or the STAC ItemCollection to be published. The STAC Item shall follow the profile and the constrains described above.

The API response will contain, in case of success, the ingested STAC Item or a STAC ItemCollection (containing the ingested STAC Item) as present in the Catalogue, thus with
- Additional required metadata, including a link to the STAC Collection
- Rewritten asset links pointing to the datastore.

The API response will contain, in case of failure, a JSON entry with the _id_ of the STAC Item to be ingested and a _failure_reason_ message for the STAC Items which failed ingestion.

Examples of API request and response are provided below. Please note that this API operation will require authorization.
  """,
  status_code=201,
  responses={
    201: {"description": "Successful addition. The added item is reported in the body (with rewritten assets HREF).","content":{"application/json":{"examples":{"Item":{"value":
      {
      "type": "Feature",
      "stac_version": "1.0.0",
      "stac_extensions": [
        "https://stac-extensions.github.io/file/v2.1.0/schema.json"
      ],
      "id": "S3A_OPER_AUX_GNSSRD_POD__20171212T193142_V20160223T235943_20160224T225600",
      "properties": {
        "start_datetime": "2015-05-19T12:00:00.000000Z",
        "end_datetime": "2015-05-20T12:00:00.000000Z"
      },
      "assets": {
        "PRODUCT": {
          "href": "http://myserver.com/d/2015/05/19/S3A_OPER_AUX_GNSSRD_POD__20171212T193142_V20160223T235943_20160224T225600/S3A_OPER_AUX_GNSSRD_POD__20171212T193142_V20160223T235943_20160224T225600.tgz",
          "title": "Product",
          "type": "application/octet-stream",
          "roles": ["data"],
          "file:checksum": "90e4021044a8995dd50b6657a037a7839304535b",
          "file:size": 153600
        }
      },
      "collection": "PRR_TEST",
      "links": []
    }},"ItemCollection":{"value":
{
  "type": "FeatureCollection",
  "features": [
    {
      "assets": {
        "PRODUCT": {
          "href": "http://myserver.com/d/2015/05/19/S3A_OPER_AUX_GNSSRD_POD__20171212T193142_V20160223T235943_20160224T225600/S3A_OPER_AUX_GNSSRD_POD__20171212T193142_V20160223T235943_20160224T225600.tgz",
          "title": "Product",
          "type": "application/octet-stream",
          "roles": ["data"],
          "file:checksum": "90e4021044a8995dd50b6657a037a7839304535b",
          "file:size": 153600
        }
      },
      "id": "S3A_OPER_AUX_GNSSRD_POD__20171212T193142_V20160223T235943_20160224T225600",
      "properties": {
        "start_datetime": "2015-05-19T12:00:00.000000Z",
        "end_datetime": "2015-05-20T12:00:00.000000Z"
      },
      "stac_extensions": [
        "https://stac-extensions.github.io/file/v2.1.0/schema.json"
      ],
      "stac_version": "1.0.0",
      "type": "Feature",
      "collection": "PRR_TEST",
      "links": []
    }
  ]
}
    }
    }}}},
    409: {"description": "Conflict. Failed to add one or more items because items already exist","content":{"application/json":{"examples":{"Item":{"value":
      {"id": "the id of the item which already exists",
       "failure_reason": "Item already exists"}
    },"ItemCollection":{"value":
{
  "type": "FeatureCollection",
  "features": [
      {"id": "the id of the item which already exists",
       "failure_reason": "Item already exists"}
  ]
}
    }}}}}, 
    422: {"description": "Validation error. Failed to add one or more items. Error in the response","content":{"application/json":{"examples":{"Item":{"value":
      {"id": "the id of the item which failed to be ingested if determined",
       "failure_reason": "a text describing the error"}
    },"ItemCollection":{"value":
{
  "type": "FeatureCollection",
  "features": [
      {"id": "the id of the item which failed to be ingested if determined",
       "failure_reason": "a text describing the error"}
  ]
}
    }}}}}
  }
)
async def collection_items_post_request(
  user_id: int = Depends(get_current_username),
  collectionId: str = Path(example="PRR_TEST"),                                          
  body: dict = Body(openapi_examples={"single":{"summary":"Item","value":{
    "type": "Feature",
    "stac_version": "1.0.0",
    "stac_extensions": [
      "https://stac-extensions.github.io/file/v2.1.0/schema.json"
    ],
    "id": "S3A_OPER_AUX_GNSSRD_POD__20171212T193142_V20160223T235943_20160224T225600",
    "properties": {
      "start_datetime": "2015-05-19T12:00:00.000000Z",
      "end_datetime": "2015-05-20T12:00:00.000000Z"
    },
    "assets": {
      "PRODUCT": {
        "href": "the/path/is/not/important/S3A_OPER_AUX_GNSSRD_POD__20171212T193142_V20160223T235943_20160224T225600.tgz",
        "title": "Product",
        "type": "application/octet-stream",
        "roles": ["data"],
        "file:checksum": "90e4021044a8995dd50b6657a037a7839304535b",
        "file:size": 153600
      }
    }
  }},
  "collection":{"summary":"ItemCollection","value":{
    "type": "FeatureCollection",
    "features": [
        {
            "assets": {
                "PRODUCT": {
                    "href": "the/path/is/not/important/S3A_OPER_AUX_GNSSRD_POD__20171212T193142_V20160223T235943_20160224T225600.tgz",
                    "title": "Product",
                    "type": "application/octet-stream",
                    "roles": ["data"],
                    "file:checksum": "90e4021044a8995dd50b6657a037a7839304535b",
                    "file:size": 153600
                }
            },
            "id": "S3A_OPER_AUX_GNSSRD_POD__20171212T193142_V20160223T235943_20160224T225600",
            "stac_extensions": [
              "https://stac-extensions.github.io/file/v2.1.0/schema.json"
            ],
            "stac_version": "1.0.0",
            "type": "Feature",
            "properties": {
              "start_datetime": "2015-05-19T12:00:00.000000Z",
              "end_datetime": "2015-05-20T12:00:00.000000Z"
            },
        }
    ],
  }}})
                                        ):
  #Check if user is authorized to the collection
  (assets_source, assets_dest, stac_dest, datastore_url,catalogue_post_url,extra_auths) = check_user_collection_authorization(user_id,collectionId)

  #Check what type of GeoJSON this is and call the ingestion accordingly
  if 'type' in body and body['type']=='Feature':
    #Single item to ingest
    ingested_item = await add_item_to_collection(assets_source,assets_dest,stac_dest,datastore_url,catalogue_post_url,collectionId,body)
    #Construct response
    response_body = ingested_item
    if 'failure_reason' in response_body:
      if response_body['failure_reason'] == 'Item already exists':
        response_status=409
      else:
        response_status=422
    else:
      response_status=201
  elif 'type' in body and body['type']=='FeatureCollection' and 'features' in body and isinstance(body['features'],list) and len(body['features'])>0:
    #Multiple items to ingest
    ingested_items = await asyncio.gather(*[add_item_to_collection(assets_source,assets_dest,stac_dest,datastore_url,catalogue_post_url,collectionId,k) for k in body['features']])
    #Construct response
    response_body = { 'type':'FeatureCollection','features':ingested_items }
    response_status=201
    for ingested in ingested_items:
      if 'failure_reason' in ingested:
        if ingested['failure_reason'] == 'Item already exists':
          response_status=409
        else:
          response_status=422
          break
  else:
    #Invalid request
    raise HTTPException(status_code=422, detail="You need to post an item of the type Feature or FeatureCollection")

  return JSONResponse(status_code=response_status,content=response_body)

def valid_id_match(strg, search=re.compile(r'[^a-zA-Z0-9._-]').search, lenmax=100):
  if len(strg)>lenmax: return False
  return not bool(search(strg))

async def add_item_to_collection(assets_source: str, assets_dest: str, stac_dest: str, datastore_url: str, catalogue_post_url: str, collectionId: str, i: dict):
  #Check for validity of the STAC
  if 'id' not in i:
    return {"id":"unknown","failure_reason":"ID is required in the STAC item to be ingested"}
  if not valid_id_match(i['id'],lenmax=100):
    return {"id":i['id'],"failure_reason":"ID field is invalid. Only [a-zA-Z0-9._-] are allowed"}
  if 'stac_extensions' not in i or not isinstance(i['stac_extensions'], list) or 'https://stac-extensions.github.io/file/v2.1.0/schema.json' not in i['stac_extensions']:
    return {"id":i['id'],"failure_reason":"STAC Extension 'https://stac-extensions.github.io/storage/v1.0.0/schema.json' is required"}
  if 'collection' not in i:
    i['collection']=collectionId
  elif i['collection']!=collectionId:
    return {"id":i['id'],"failure_reason":"Collection ID contained in the STAC JSON is different from the one in the POST"}
  if 'links' not in i:
    #Add default empty links
    i['links']=[]
  if 'geometry' not in i:
    #Add default empty geometry
    i['geometry']=None
  if 'properties' not in i:
    return {"id":i['id'],"failure_reason":"Missing required property field from the STAC JSON"}
  if 'start_datetime' not in i['properties']: return {"id":i['id'],"failure_reason":"Missing required start_datetime from the STAC JSON"}
  if 'end_datetime' not in i['properties']: return {"id":i['id'],"failure_reason":"Missing required end_datetime from the STAC JSON"}
  if 'datetime' not in i['properties'] or i['properties']['datetime'] is None:
    i['properties']['datetime']=i['properties']['start_datetime']
  for a in ['start_datetime','end_datetime','datetime']:
    try:
      item_datetime_str_orig=i['properties'][a]
      item_datetime_obj=dt.datetime.fromisoformat(item_datetime_str_orig)
      item_datetime_str_new=item_datetime_obj.strftime('%Y-%m-%dT%H:%M:%SZ')
    except Exception as e:
      return {"id":i['id'],"failure_reason":f"Failed to parse product date time. {item_datetime_str_orig} is an invalid ISO time"}
  #Extract all the local assets (and check that they are available)
  if not 'assets' in i:
    #Error, one asset at least is mandatory
    return {"id":i['id'],"failure_reason":f"No assets provided. At least one asset with role 'data' or 'documentation' is mandatory."}
    
  #Scan the assets to check for compliancy and flag directory and file assets to be moved
  assets_dict=i['assets']
  #Check at least one asset with role 'data' or 'documentation' role is provided
  data_is_present=False
  assets_to_move={}
  for asset_key in assets_dict:
    asset=assets_dict[asset_key]

    #Check mandatory metadata for the asset are provided
    mandatory_metadata={'href':str,'type':str,'roles':list,'file:size':int}
    for a in mandatory_metadata:
      if a not in asset: return {"id":i['id'],"failure_reason":f"{asset_key} asset does not have the mandatory '{a}' metadata."}
      if not isinstance(asset[a],mandatory_metadata[a]): return {"id":i['id'],"failure_reason":f"{asset_key} asset metadata '{a}' is invalid."}
    #Check asset has 'data' or 'documentation' role
    if not data_is_present and ('data' in asset['roles'] or 'documentation' in asset['roles']):
      data_is_present=True

    #Skip URLs and assets who do not have HREF from the assets to be moved
    if '://' in asset['href']:
      continue

    #Get the absolute path to the asset
    staging_asset_path=os.path.normpath(os.path.join(assets_source,asset['href']))
    if not staging_asset_path.startswith(assets_source):
      #You are trying to escape the assets_source path
      return {"id":i['id'],"failure_reason":f"{asset_key} asset {asset['href']} is out of the staging area"}
    #Check if the assets exist in the storage
    try:
      statinfo = os.stat(staging_asset_path)
    except FileNotFoundError:
      return {"id":i['id'],"failure_reason":f"{asset_key} asset {asset['href']} not found in the staging area location"}
    #We behave differently if this is a file or a directory
    if stat.S_ISREG(statinfo.st_mode):
      #This is a regular file
      #Check the file size
      if stat.S_ISREG(statinfo.st_mode) and statinfo.st_size != asset['file:size']:
        return {"id":i['id'],"failure_reason":f"Asset {asset_key} is invalid. File size does not match the one of the file in the S3 stagein path"}
      assets_to_move[staging_asset_path]=asset_key
    elif stat.S_ISDIR(statinfo.st_mode):
      #This is a directory, ensure it has a / at the end (normpath has removed it)
      assets_to_move[staging_asset_path+os.sep]=asset_key
    else:
      return {"id":i['id'],"failure_reason":f"{asset_key} asset {asset['href']} is not a file nor a directory."}
    #Check if the checksum format is valid (if checksum is specified)
    if 'file:checksum' in asset:
      # Must be non-empty and contain only lowercase hex digits.
      s=asset['file:checksum']
      if len(s)<2 or (len(s) % 2) or any(c not in "0123456789abcdef" for c in s):
        return {"id":i['id'],"failure_reason":f"{asset_key} asset {asset['href']} has invalid checksum metadata (not valid lowecase hex string)."}
      try:
        mh = bytes.fromhex(s)
      except ValueError:
        return {"id":i['id'],"failure_reason":f"{asset_key} asset {asset['href']} has invalid checksum metadata (decoding hex string failed)."}
      # Check the hash type is supported
      if mh[0] != 0x11 and mh[0] != 0x12 and mh[0] != 0x13:
        return {"id":i['id'],"failure_reason":f"{asset_key} asset {asset['href']} has invalid checksum metadata (only hashing algorithms sha1, sha256 and sha512 are supported)."}
      # Check digest lenght is valid
      if len(mh)-2 != mh[1]:
        return {"id":i['id'],"failure_reason":f"{asset_key} asset {asset['href']} has invalid checksum metadata (invalid digest lenght. Should be {mh[1]}, is {len(mh)-2})."}

  #Error if we do not have one asset with the role data nor documentation
  if data_is_present == False:
    return {"id":i['id'],"failure_reason":f"At least one asset with role 'data' or 'documentation' is mandatory."}

  #Determine where to move the assets. Destination for the asset is calculated using the collection and the asset start time if present. This is to not overload the file system with too many assets and have one unique way of representing assets in the datastore.
  assets_base_date=dt.datetime.fromisoformat(i['properties']['datetime']).strftime(f'%Y{os.sep}%m{os.sep}%d')
  assets_base_path=os.path.join(assets_base_date,i["id"])
  assets_to_move_src=[]
  assets_to_move_dst=[]
  last_assed_move_src=None
  last_assed_move_href=None
  for staging_asset_path in sorted(assets_to_move):
    asset_key=assets_to_move[staging_asset_path]
    if last_assed_move_src==None or not staging_asset_path.startswith(last_assed_move_src):
      #The asset has to me moved
      #Determine its id
      if staging_asset_path[-1]=='/': staging_asset_path=staging_asset_path[:-1]
      staging_asset_filename=os.path.basename(staging_asset_path)
      if not valid_id_match(staging_asset_filename,lenmax=100):
        return {"id":i['id'],"failure_reason":f"Asset {asset_key} file name is invalid. Only [a-zA-Z0-9._-] are allowed"}

      #Determine destination for the asset in the data store, this is used for both the access URL and the datastore destination path below
      ds_asset_path=os.path.join(assets_base_path,staging_asset_filename)
      assets_to_move_src.append(staging_asset_path)
      staging_asset_path_dest=os.path.join(assets_dest,ds_asset_path)
      if staging_asset_path_dest in assets_to_move_dst:
        return {"id":i['id'],"failure_reason":f"Asset {asset_key} file name is not unique. Another asset in the product has the same file name"}
      assets_to_move_dst.append(staging_asset_path_dest)

      #Rewrite the asset URL to make it point to the stagein and save for next asset
      last_assed_move_src=staging_asset_path
      last_assed_move_href=datastore_url+ds_asset_path
      i['assets'][asset_key]['href']=datastore_url+ds_asset_path
    else:
      #The asset is in a directory which has been already moved
      #Just rewrite the asset
      i['assets'][asset_key]['href']=last_assed_move_href+staging_asset_path[len(last_assed_move_src):]
    
    #Error if we do not have one asset with the role data nor documentation
    if data_is_present == False:
      return {"id":i['id'],"failure_reason":f"At least one asset with role 'data' or 'documentation' is mandatory."}
  #Post the STAC Item to the catalogue
  #Construct catalogue request
  stac_item=json.dumps(i).encode("utf-8")
  req = URLlibRequest(catalogue_post_url, stac_item, headers={'Content-Type':'application/geo+json'}, method='POST')
  try:
    response = URLlibUrlopen(req)
  except HTTPError as e:
    if e.code==409:
      return {"id":i['id'],"failure_reason":f"Item already exists"}
    else:
      response_text=e.read().decode('utf-8')
      response_status=str(e)
      return {"id":i['id'],"failure_reason":f"Catalogue refused STAC: {response_status}: {response_text}"}
  except URLError as e:
    response_status='URLError'
    response_text=str(e)
    return {"id":i['id'],"failure_reason":f"Catalogue refused STAC: {response_status}: {response_text}"}
  except Exception as e:
    response_status='Exception'
    response_text=str(e)
    return {"id":i['id'],"failure_reason":f"Catalogue refused STAC: {response_status}: {response_text}"}

  #Now save STAC item
  backup_stac_item=os.path.join(os.path.join(stac_dest,assets_base_date),i['id'])
  try:
    os.makedirs(os.path.dirname(backup_stac_item), exist_ok=True)
    with open(backup_stac_item,'wb') as f:
      f.write(stac_item)
  except Exception as e:
    response_status='Exception'
    response_text=str(e)
    return {"id":i['id'],"failure_reason":f"Failed to store STAC in datastore: {response_status}: {response_text}"}

  #And move output
  for idx,asset_src in enumerate(assets_to_move_src):
    asset_dst=assets_to_move_dst[idx]
    try:
      #Move file
      os.makedirs(os.path.dirname(asset_dst), exist_ok=True)
      os.rename(asset_src,asset_dst)
    except Exception as e:
      response_status='Exception'
      response_text=str(e)
      return {"id":i['id'],"failure_reason":f"Failed to store asset {os.path.basename(asset_dst)} in datastore: {response_status}: {response_text}"}

  #All ok, return the updated product
  return i

@app.delete(
  "/collections/{collectionId}/items/{recordId}",
  tags=["Implemented transaction operations:"],
  summary="Delete an Item or an ItemCollection from a collection",
  description="""This call allows to **delete** a STAC Item or ItemCollection from the catalogue and datastore.

Please note that this action cannot be reversed, and it will delete all the assets from the catalogue and datastore including all backups. It should be used with lots of caution and for testing only.

Please note that this API will require special authorization. **Only administrators should be able to use it.**""",
  status_code=201,
  responses={
      201: {"description": "Successful deletion.","content":{"application/json":{"examples":{"Item":{"value":
      {"id": "the id of the item deleted",
       "message": "deleted"}
      }}}}},
      404: {"description": "Product not foind.","content":{"application/json":{"examples":{"Item":{"value":
      {"id": "the id of the item to be deleted",
       "message": "Item not found"}
      }}}}},
      422: {"description": "Validation error. Failed to delete one or more items. Error in the response","content":{"application/json":{"examples":{"Item":{"value":
      {"id": "the id of the item to be deleted",
       "failure_reason": "a test describing the error"}
      }}}}}
    }
)
async def collection_items_del_request(
  user_id: int = Depends(get_current_username),
  collectionId: str = Path(example="PRR_TEST"),
  recordId: str = Path(example="S3A_OPER_AUX_GNSSRD_POD__20171212T193142_V20160223T235943_20160224T225600")):

  #Check if user is authorized to delete from the collection
  (assets_source, assets_dest, stac_dest, datastore_url,catalogue_post_url,extra_auths) = check_user_collection_authorization(user_id,collectionId)
  if extra_auths % 2 == 0:
    raise HTTPException(status_code=422, detail="User is not authorized to delete items in this collection")

  #Final failure reason
  failure_reason=''

  #Get the product from the catalogue (and also check it is actually there)
  req = URLlibRequest(os.path.join(catalogue_post_url,recordId), headers={'Content-Type':'application/geo+json'}, method='GET')
  try:
    response = URLlibUrlopen(req)
  except HTTPError as e:
    if e.code==404:
      raise HTTPException(status_code=404, detail={"id":recordId,"failure_reason":"Item not found"})
    else:
      response_text=e.read().decode('utf-8')
      response_status=str(e)
      failure_reason=f"Catalogue refused GET: {response_status}: {response_text}"
  except URLError as e:
    response_status='URLError'
    response_text=str(e)
    failure_reason=f"Catalogue refused GET: {response_status}: {response_text}"
  except Exception as e:
    response_status='Exception'
    response_text=str(e)
    failure_reason=f"Catalogue refused GET: {response_status}: {response_text}"
  if failure_reason!='':
    raise HTTPException(status_code=422, detail=failure_reason)
  try:
    i=json.loads(response.read())
  except Exception as e:
    response_status='Exception'
    response_text=str(e)
    failure_reason=f"Catalogue refused GET: {response_status}: {response_text}"
    raise HTTPException(status_code=422, detail=failure_reason)

  #Extract datetime and determine paths of products to delete
  if 'properties' not in i:
    raise HTTPException(status_code=422, detail={"id":i['id'],"failure_reason":"Missing required property field from the STAC JSON"})
  if 'datetime' not in i['properties'] or i['properties']['datetime'] is None:
    if 'start_datetime' in i['properties']:
      item_datetime_str=i['properties']['start_datetime']
    else:
      raise HTTPException(status_code=422, detail={"id":i['id'],"failure_reason":"datetime or start_datetime properties are mandatory"})
  else:
    item_datetime_str=i['properties']['datetime']
  try:
    item_datetime_obj=dt.datetime.fromisoformat(item_datetime_str)
  except Exception as e:
    raise HTTPException(status_code=422, detail={"id":i['id'],"failure_reason":"Failed to parse product date time. {item_datetime_str} is an invalid ISO time"})
  assets_base_date=item_datetime_obj.strftime(f'%Y{os.sep}%m{os.sep}%d')
  assets_base_path=os.path.join(assets_base_date,i["id"])
  assets_path_to_delete=os.path.join(assets_dest,assets_base_path)
  stacs_path_to_delete=os.path.join(os.path.join(stac_dest,assets_base_date),i['id'])

  #Delete element form the catalogue collection
  req = URLlibRequest(os.path.join(catalogue_post_url,recordId), headers={'Content-Type':'application/geo+json'}, method='DELETE')
  try:
    response = URLlibUrlopen(req)
  except HTTPError as e:
    response_text=e.read().decode('utf-8')
    response_status=str(e)
    failure_reason=f"Catalogue refused DELETE: {response_status}: {response_text}"
  except URLError as e:
    response_status='URLError'
    response_text=str(e)
    failure_reason=f"Catalogue refused DELETE: {response_status}: {response_text}"
  except Exception as e:
    response_status='Exception'
    response_text=str(e)
    failure_reason=f"Catalogue refused DELETE: {response_status}: {response_text}"
  if failure_reason!='':
    raise HTTPException(status_code=422, detail=failure_reason)

  #Delete STAC Item backup
  if os.path.exists(stacs_path_to_delete):
    os.remove(stacs_path_to_delete)
  else:
    failure_reason='Cannot delete STAC Item backup. It does not exist.'
  #Delete STAC assets
  if os.path.exists(assets_path_to_delete):
    shutil.rmtree(assets_path_to_delete)
  else:
    failure_reason=failure_reason+'Cannot delete STAC Item Assets. They do not exist.'

  #Return result
  if failure_reason=='':
    return JSONResponse(status_code=201,content={"id":recordId,"message":"deleted"})
  else:
    raise HTTPException(status_code=422, detail=failure_reason)
