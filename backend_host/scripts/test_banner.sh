#!/bin/bash

# Load environment variables from .env file
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ENV_FILE="$PROJECT_ROOT/.env"

if [ ! -f "$ENV_FILE" ]; then
    echo "❌ Error: .env file not found at $ENV_FILE"
    exit 1
fi

# Load OPENROUTER_API_KEY from .env file
OPENROUTER_API_KEY=$(grep "^OPENROUTER_API_KEY=" "$ENV_FILE" | cut -d'=' -f2 | tr -d '\r\n')

if [ -z "$OPENROUTER_API_KEY" ]; then
    echo "❌ Error: OPENROUTER_API_KEY not found in .env"
    exit 1
fi

echo "✅ Loaded API key from $ENV_FILE"
echo ""

curl -X POST "https://openrouter.ai/api/v1/chat/completions" \
  -H "Authorization: Bearer $OPENROUTER_API_KEY" \
  -H "Content-Type: application/json" \
  -H "HTTP-Referer: https://virtualpytest.com" \
  -H "X-Title: VirtualPyTest" \
  -d '{
    "model": "qwen/qwen-2.5-vl-7b-instruct",
    "messages": [
      {
        "role": "user",
        "content": [
          {
            "type": "text",
            "text": "Analyze this TV screen image to extract channel and program information.\n\nWHAT YOU'\''RE LOOKING FOR:\nYou need to identify ANY visible channel information display, including:\n- Channel logos or names (e.g., \"BBC One\", \"U&DRAMA\", \"ITV\", \"Channel 4\")\n- Program/show titles (e.g., \"New Tricks\", \"EastEnders\", \"News\")\n- Episode information (e.g., \"S 2, Ep 7 - Fluke of Luck\")\n- Time information (e.g., \"00:15 - 01:35\", \"18:00 - 19:00\")\n\nIMPORTANT: Set \"banner_detected\": true if you can see ANY of the following:\n✓ Channel logo or name visible anywhere in the image\n✓ Program title displayed with time information\n✓ Episode information with channel branding\n✓ TV player UI showing channel and program details\n✓ Any on-screen display (OSD) with channel/program info\n\nThis includes:\n- Player overlays showing program information\n- Channel banners that appear during channel changes\n- Program guide information bars\n- Corner logos with program details\n- ANY text showing what channel/program is playing\n\nRequired JSON format (if channel info found):\n{\n  \"banner_detected\": true,\n  \"channel_name\": \"U&DRAMA\",\n  \"channel_number\": \"\",\n  \"program_name\": \"New Tricks\",\n  \"episode_information\": \"S 2, Ep 7 - Fluke of Luck\",\n  \"start_time\": \"00:15\",\n  \"end_time\": \"01:35\",\n  \"confidence\": 0.85\n}\n\nIf NO channel or program information visible:\n{\n  \"banner_detected\": false,\n  \"channel_name\": \"\",\n  \"channel_number\": \"\",\n  \"program_name\": \"\",\n  \"episode_information\": \"\",\n  \"start_time\": \"\",\n  \"end_time\": \"\",\n  \"confidence\": 0.1\n}\n\nEXTRACTION RULES:\n- Channel name: Look in ALL corners, especially top-left and top-right for logos/text\n- Channel number: Usually appears before/near the channel name (e.g., \"101 BBC One\")\n- Program name: Main title text (e.g., \"New Tricks\"), do NOT include episode info here\n- Episode information: Season/episode details (e.g., \"S 2, Ep 7 - Fluke of Luck\") - extract separately!\n- Start/end times: Format as HH:MM (e.g., \"18:00\", \"01:35\")\n- If you see a channel logo without explicit channel number, leave channel_number empty\n\nCONFIDENCE SCORING:\n- 0.9-1.0: Channel name/logo + program name + time all clearly visible\n- 0.7-0.9: Channel name/logo + program name visible (time optional)\n- 0.5-0.7: Only channel name/logo OR only program name visible\n- 0.3-0.5: Partial/unclear channel information\n- 0.0-0.3: No clear channel information\n\nCRITICAL: You MUST respond with valid JSON. Never return empty content.\n\nRESPOND ONLY WITH THE JSON OBJECT - NO MARKDOWN BLOCKS - NO EXPLANATION."
          },
          {
            "type": "image_url",
            "image_url": {
              "url": "data:image/jpeg;base64,'"$(cat /tmp/banner_b64_test.txt)"'"
            }
          }
        ]
      }
    ],
    "max_tokens": 600,
    "temperature": 0.0
  }' | python3 -m json.tool