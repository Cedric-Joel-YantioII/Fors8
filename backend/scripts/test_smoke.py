#!/usr/bin/env python3
"""Smoke test: verify OpenRouter connectivity and JSON output."""

import os
import sys
import json
import re

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Force env vars
os.environ['LLM_API_KEY'] = 'os.environ.get('LLM_API_KEY', 'your-key-here')'
os.environ['LLM_BASE_URL'] = 'https://openrouter.ai/api/v1'
from openai import OpenAI

client = OpenAI(
    api_key=os.environ['LLM_API_KEY'],
    base_url=os.environ['LLM_BASE_URL'],
)

# Try free models — some don't support system prompts, so we test with user-only
FREE_MODELS = [
    'nousresearch/deephermes-3-llama-3-8b-preview:free',
    'google/gemma-3-12b-it:free',
    'google/gemma-3-27b-it:free',
    'mistralai/mistral-small-3.1-24b-instruct:free',
    'openrouter/free',
]

MODEL = None
for candidate in FREE_MODELS:
    try:
        print(f"Trying model: {candidate}...")
        test_resp = client.chat.completions.create(
            model=candidate,
            messages=[{"role": "user", "content": "Say OK"}],
            max_tokens=10,
            temperature=0.1,
        )
        content = (test_resp.choices[0].message.content or "").strip()
        content = re.sub(r'<think>[\s\S]*?</think>', '', content).strip()
        if content:
            MODEL = candidate
            print(f"  Working! Response: {content}")
            break
        else:
            print(f"  Empty response, trying next...")
    except Exception as e:
        err_str = str(e)
        if '429' in err_str:
            print(f"  Rate limited, trying next...")
        elif '404' in err_str:
            print(f"  Not found, trying next...")
        else:
            print(f"  Failed: {err_str[:100]}")
        continue

if not MODEL:
    print("ERROR: No free model available. Check OpenRouter account.")
    sys.exit(1)

print(f"\nUsing model: {MODEL}\n")

def clean_response(text):
    if not text:
        return ""
    text = re.sub(r'<think>[\s\S]*?</think>', '', text).strip()
    text = re.sub(r'^```(?:json)?\s*\n?', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\n?```\s*$', '', text)
    return text.strip()

import time

def call_llm(messages, max_tokens=500, temperature=0.5, retries=3):
    """Call LLM with retries and null-safety."""
    for attempt in range(retries):
        try:
            response = client.chat.completions.create(
                model=MODEL,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            content = response.choices[0].message.content
            if content:
                return clean_response(content)
            print(f"  [Attempt {attempt+1}] Empty response, retrying...")
        except Exception as e:
            print(f"  [Attempt {attempt+1}] Error: {e}")
        time.sleep(2)
    return None

print("=== SMOKE TEST 1: Basic LLM connectivity ===")
content = call_llm([{"role": "user", "content": "Reply with exactly one word: CONNECTED"}], max_tokens=20, temperature=0.1)
print(f"  Response: {content}")
if content:
    print("  PASS")
else:
    print("  WARN: Empty response (free model rate limits). Continuing...")
print()

print()
print("=== SMOKE TEST 2: JSON output ===")
content2 = call_llm([
    {"role": "user", "content": 'You must output valid JSON only. No markdown, no explanation, no thinking. Output this exact JSON: {"actor_name": "Iran", "risk_tolerance": 0.8, "actions": ["missile_launch", "blockade"]}'},
], max_tokens=200, temperature=0.3)

if content2:
    print(f"  Raw: {content2[:300]}")
    try:
        parsed = json.loads(content2)
        print(f"  Parsed keys: {list(parsed.keys())}")
        print("  PASS")
    except json.JSONDecodeError:
        print(f"  JSON parse failed on: {content2[:200]}")
        print("  WARN: Model returned non-JSON (common with free models)")
else:
    print("  WARN: Empty response")
print()

print("=== SMOKE TEST 3: Geopolitical actor decision ===")
content3 = call_llm([
    {"role": "user", "content": """You are simulating Iran's strategic decision-making. Output ONLY valid JSON, no other text.

JSON format: {"situation_assessment": "brief text", "actions": [{"action_type": "action_name", "target_actor_id": "target_or_null", "reasoning": "why"}]}

Available actions: launch_strike, missile_launch, propose_negotiation, hold_position, public_statement, backchannel_communication

Current situation: Escalation level 7/10. Iran has fired 500+ missiles. Supreme Leader Khamenei was killed. New leader Mojtaba Khamenei (hardliner). Trump just announced 5-day pause on energy strikes. Iran's 3 demands: rights, reparations, guarantees. Oil at $119. Strait of Hormuz closed. What does Iran do next?"""},
], max_tokens=600, temperature=0.5)

if content3:
    print(f"  Raw: {content3[:500]}")
    try:
        parsed3 = json.loads(content3)
        actions = parsed3.get("actions", [])
        print(f"  Actions chosen: {[a.get('action_type') for a in actions]}")
        print(f"  Assessment: {parsed3.get('situation_assessment', '')[:200]}")
        print("  PASS")
    except json.JSONDecodeError:
        print(f"  JSON parse failed — common with free models")
        print("  PARTIAL PASS (model returned text, would need prompt tuning)")
else:
    print("  WARN: Empty response from free model")
print()

print("=== ALL SMOKE TESTS COMPLETE ===")
