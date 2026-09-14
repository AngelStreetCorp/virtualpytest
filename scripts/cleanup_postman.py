#!/usr/bin/env python3
"""
Clean up all Postman specs and collections in the VirtualPyTest workspace
"""
import os
import requests
from dotenv import load_dotenv

# Load environment variables
load_dotenv(encoding='utf-8-sig')

API_KEY = os.getenv('POSTMAN_API_KEY')
if not API_KEY:
    print("❌ POSTMAN_API_KEY not found in environment")
    exit(1)

WORKSPACE_ID = "91dbec69-5756-413d-a530-a97b9cadf615"
BASE_URL = "https://api.postman.com"

headers = {
    'X-Api-Key': API_KEY,
    'Content-Type': 'application/json'
}

# Specs to delete (all 25)
spec_ids = [
    "4a7aacdb-cb30-416f-985c-26d6c46ca0b7",  # SERVER - Metrics Analytics
    "c2ba47c5-82fd-4926-a875-d8febf0abf02",  # SERVER - System
    "979357a3-24cb-45f7-8b84-45b537c271d3",  # SERVER - User Interface
    "a3834ba3-2695-4826-80bb-83f053ee263a",  # SERVER - Deployment Scheduling
    "a4eb4a33-0ea3-4802-928f-f76003357af4",  # SERVER - Requirements
    "6ec16f83-3c97-41eb-8999-b35f81759230",  # SERVER - AI Analysis
    "6fb05971-5bbd-4f60-9146-c1843bf1e343",  # SERVER - Navigation
    "ca661016-63a7-4cfe-87cf-898f8ba7930f",  # SERVER - Testcase
    "a1144bc2-a99a-4156-b547-d2e5c60c4ad0",  # SERVER - Campaign
    "f46bc870-5376-4c10-a618-6136e9f27804",  # SERVER - Device
    "7b40fb86-6ab7-4c04-943a-654766b84a30",  # SERVER - Script
    "b02534c3-f5dc-425e-acf5-9edaf9f32bd8",  # VirtualPyTest - Testcase Execution
    "e42eda2e-d046-461f-9c31-d8a991711157",  # VirtualPyTest - User Interface
    "dde5b7e6-4b92-49d7-9f6a-1ebde263c2bf",  # VirtualPyTest - Deployment & Scheduling
    "77c15aaa-f04a-4584-8bc3-34b7f2185388",  # VirtualPyTest - Metrics & Analytics
    "f3fb66c6-a7ce-46fd-885e-ebbdb07f6c51",  # VirtualPyTest - Requirements
    "afa2b34c-2802-41f2-b8ae-e01c6331572b",  # VirtualPyTest - AI Exploration
    "e1ef3690-24a8-4dff-84a3-1a10f2f51d9d",  # VirtualPyTest - Verification Suite
    "42f978c7-b2ef-4673-8c82-69dbe7581dea",  # VirtualPyTest - AI Analysis
    "2615abf6-2613-4a22-b058-c85603fa3efd",  # VirtualPyTest - Script
    "b51b8d1c-7bd5-4f7c-9a7e-61ea7dfd62e3",  # VirtualPyTest - Testcase
    "da4b8bfc-565e-46d8-bbda-d76234430b46",  # VirtualPyTest - Navigation
    "e73f30d2-9c3e-4670-a72a-46cf9d14b187",  # VirtualPyTest - System
    "d75354a3-6e8c-4c55-b401-49d83d3a5718",  # VirtualPyTest - Campaign
    "f2193488-7d68-46e7-a480-dca6462e892a",  # VirtualPyTest - Device
]

# Collections to delete (all 32)
collection_uids = [
    "50408747-02dad45d-3c67-446a-918b-df5edbdd07ac",
    "50408747-0b6297ca-f9cf-4195-b5d5-f8c4ddecc49e",
    "50408747-0d39c723-518d-4ec6-8085-d28722af2e79",
    "50408747-182fe23c-3968-4ce2-aa18-9a0df1389a4d",
    "50408747-19399375-c6db-463c-a77e-3844c45076dd",
    "50408747-1e11e07a-b68b-4d6b-8c67-f7669a0473ff",
    "50408747-386ce4b3-afb5-4f4c-b831-7feaab51f39c",
    "50408747-46bde30a-1b3a-46ed-8248-263ea79d8134",
    "50408747-4b6e52ee-e8d0-4eae-8392-e7d8ae31489f",
    "50408747-553b4029-6af1-4151-a10a-9594ee75dd6e",
    "50408747-70e85a29-5d49-4c0b-b94e-c829e87a07db",
    "50408747-772dba79-8307-4c78-b3e9-c8c180a67fb7",
    "50408747-7fce75f1-4510-46b3-bb08-641b5463cde0",
    "50408747-8a68d2fc-438f-4ed1-9c4b-81e693cf5395",
    "50408747-91fc31ac-0a25-4e01-8e9f-5123477a891d",
    "50408747-9a2e5467-8178-455e-b17c-b9fb5f98007d",
    "50408747-a45bf22b-e4c2-47a1-bda8-5c2e9651e9e5",
    "50408747-b0904672-54d5-46dd-b962-c7a72d752462",
    "50408747-bb858f56-fb80-4896-a804-fa02e716e439",
    "50408747-c1d15773-d440-4022-a841-86266ae75d9c",
    "50408747-c5d1e382-a2f6-4beb-8774-c8bcca03ab26",
    "50408747-cce2607c-ef19-4ba4-9c9f-301d602b9dba",
    "50408747-cd0b4889-e3df-4e31-bd12-7357c79ce6d2",
    "50408747-d434ffc4-f59e-4b70-b899-a2cbdf39e542",
    "50408747-d600c890-8b11-42a4-9022-c0af48f7d157",
    "50408747-d8b76db5-3730-419f-828f-e64ea2ad5226",
    "50408747-dd26d37a-39cb-4cd5-840e-1d74e92dc41a",
    "50408747-dd6df8c6-3014-4923-8ec3-f888eb0e4184",
    "50408747-ed47e650-da36-40bc-9abb-012146ca30d3",
    "50408747-ef97e08d-6cdc-432e-a27b-f52e9d52a3c2",
    "50408747-f415db70-d982-41cc-b2d9-2e19906244bd",
    "50408747-faf68cf4-6af3-4a70-9202-bb1b6760537d",
]

print("🗑️  Starting cleanup...")
print(f"📊 Specs to delete: {len(spec_ids)}")
print(f"📁 Collections to delete: {len(collection_uids)}")
print()

# Delete specs
print("Deleting specs...")
for i, spec_id in enumerate(spec_ids, 1):
    try:
        response = requests.delete(
            f"{BASE_URL}/specs/{spec_id}",
            headers=headers
        )
        if response.status_code in [200, 204]:
            print(f"  ✅ [{i}/{len(spec_ids)}] Deleted spec: {spec_id[:8]}...")
        else:
            print(f"  ⚠️  [{i}/{len(spec_ids)}] Failed to delete spec {spec_id[:8]}...: {response.status_code}")
    except Exception as e:
        print(f"  ❌ [{i}/{len(spec_ids)}] Error deleting spec {spec_id[:8]}...: {e}")

print()

# Delete collections
print("Deleting collections...")
for i, collection_uid in enumerate(collection_uids, 1):
    try:
        response = requests.delete(
            f"{BASE_URL}/collections/{collection_uid}",
            headers=headers
        )
        if response.status_code in [200, 204]:
            print(f"  ✅ [{i}/{len(collection_uids)}] Deleted collection: {collection_uid[-12:]}")
        else:
            print(f"  ⚠️  [{i}/{len(collection_uids)}] Failed to delete collection {collection_uid[-12:]}: {response.status_code}")
    except Exception as e:
        print(f"  ❌ [{i}/{len(collection_uids)}] Error deleting collection {collection_uid[-12:]}: {e}")

print()
print("✨ Cleanup complete!")


