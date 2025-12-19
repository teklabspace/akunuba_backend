"""List all Persona templates via API to find the correct template ID"""
import os
import httpx
from dotenv import load_dotenv

load_dotenv()

persona_api_key = os.getenv("PERSONA_API_KEY")

if not persona_api_key:
    print("❌ PERSONA_API_KEY is not set")
    exit(1)

base_url = "https://withpersona.com/api/v1"
headers = {
    "Authorization": f"Bearer {persona_api_key}",
    "Content-Type": "application/json",
    "Persona-Version": "2024-01-01"
}

print("=" * 70)
print("Listing All Persona Templates via API")
print("=" * 70)
print(f"API Key: {persona_api_key[:30]}...")
print(f"Making request to: {base_url}/inquiry-templates")
print()

try:
    response = httpx.get(
        f"{base_url}/inquiry-templates",
        headers=headers,
        timeout=30.0
    )
    
    print(f"\nStatus Code: {response.status_code}\n")
    
    if response.status_code == 200:
        data = response.json()
        templates = data.get("data", [])
        
        if not templates:
            print("❌ No templates found")
        else:
            print(f"✅ Found {len(templates)} template(s):\n")
            print("-" * 70)
            
            for i, template in enumerate(templates, 1):
                template_id = template.get("id")
                attributes = template.get("attributes", {})
                name = attributes.get("name", "Unnamed")
                description = attributes.get("description", "")
                
                print(f"\n{i}. Template Name: {name}")
                print(f"   Template ID: {template_id}")
                if description:
                    print(f"   Description: {description[:100]}")
                
                # Check if it's the right format
                if template_id.startswith("tmpl_") or template_id.startswith("blu_"):
                    print(f"   ✅ CORRECT FORMAT - Use this one!")
                else:
                    print(f"   ⚠️  Wrong format (should start with tmpl_ or blu_)")
            
            print("\n" + "=" * 70)
            print("\n💡 Look for templates that start with 'tmpl_' or 'blu_'")
            print("   Those are the ones you can use with the API.")
            
    elif response.status_code == 401:
        print("❌ 401 Unauthorized - API key is invalid or expired")
        print("   Please check your PERSONA_API_KEY in .env file")
    else:
        print(f"❌ Error: {response.status_code}")
        try:
            error_json = response.json()
            print(f"Error details: {error_json}")
        except:
            print(f"Response: {response.text[:500]}")
            
except httpx.HTTPStatusError as e:
    print(f"❌ HTTP Error: {e.response.status_code}")
    try:
        error_json = e.response.json()
        print(f"Error: {error_json}")
    except:
        print(f"Response: {e.response.text[:500]}")
except Exception as e:
    print(f"❌ Exception: {str(e)}")

print("\n" + "=" * 70)

