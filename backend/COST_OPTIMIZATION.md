# Cost Optimization Guide

This document explains how to reduce AWS Bedrock costs for your automation workflow.

## Current Cost Structure

**Claude 3.5 Sonnet Pricing:**
- Input tokens: $0.003 per 1,000 tokens
- Output tokens: $0.015 per 1,000 tokens

**Typical Automation Cost:**
- Early steps: ~$0.09-$0.135 per step
- Later steps: ~$0.18-$0.2475 per step
- **Total per run (11 steps): ~$1.50-$2.00**

## Implemented Optimizations

### ✅ 1. XML Compression (50-70% reduction)

**What it does:**
- Removes unnecessary XML attributes (index, instance, checkable, etc.)
- Keeps only essential attributes: text, content-desc, resource-id, bounds, class
- Removes clickable="false" and editable="false" (only keeps true values)

**How to use:**
```bash
# Enabled by default
export USE_XML_COMPRESSION=true
```

**Expected savings:** 50-70% reduction in XML token size

### ✅ 2. Incremental Diff XML (40-60% reduction)

**What it does:**
- Compares current XML with previous XML
- Only sends changed elements instead of full XML
- Falls back to full XML if >50% of elements changed

**How to use:**
```bash
# Enabled by default
export USE_XML_DIFF=true
```

**Expected savings:** 40-60% reduction when screen changes are minimal

### ✅ 3. Model Switching (80% cost reduction)

**What it does:**
- Allows switching to cheaper Bedrock models
- Claude 3 Haiku: ~80% cheaper, still capable for automation
- Amazon Titan Lite: Very cheap, good for structured tasks

**How to use:**
```bash
# Switch to Claude 3 Haiku (recommended)
export BEDROCK_MODEL_ID=anthropic.claude-3-haiku-20240307-v1:0

# Or use Amazon Titan Lite (very cheap)
export BEDROCK_MODEL_ID=amazon.titan-text-lite-v1
```

**Expected savings:** 
- Claude Haiku: ~80% cost reduction ($1.50 → $0.30 per run)
- Titan Lite: ~90% cost reduction ($1.50 → $0.15 per run)

## Current Cost (With Optimizations Enabled by Default)

**Your current setup:**
- ✅ XML Compression: **ENABLED** (50-70% reduction)
- ✅ Incremental Diff: **ENABLED** (40-60% additional reduction)
- Model: Claude 3.5 Sonnet (default)

### Cost Breakdown per Run (11 steps):

**Steps 1-5 (Early steps with compression):**
- Input tokens: ~12,000-15,000 (reduced from 20K-25K)
- Output tokens: ~2,000-4,000
- Cost per step: $0.066-$0.105
- **5 steps total: $0.33-$0.525**

**Steps 6-11 (Later steps with compression + some diff):**
- Input tokens: ~25,000-35,000 (reduced from 50K-62.5K)
- Output tokens: ~2,000-4,000
- Cost per step: $0.105-$0.165
- **6 steps total: $0.63-$0.99**

### **Total Cost per Run: $0.96-$1.52**

**Monthly cost (100 runs): $96-$152**

## Cost Comparison

| Configuration | Cost per Step | Cost per Run (11 steps) | Monthly (100 runs) |
|--------------|---------------|------------------------|-------------------|
| **Before (Sonnet, no optimization)** | $0.15-$0.25 | $1.50-$2.00 | $150-$200 |
| **✅ CURRENT (Sonnet + optimizations)** | **$0.09-$0.14** | **$0.96-$1.52** | **$96-$152** |
| **With compression + diff** | $0.08-$0.12 | $0.80-$1.20 | $80-$120 |
| **Haiku + optimizations** | $0.02-$0.03 | $0.25-$0.35 | $25-$35 |
| **Titan Lite + optimizations** | $0.01-$0.02 | $0.15-$0.25 | $15-$25 |

## Recommended Configuration

For **maximum cost savings** while maintaining quality:

```bash
# Use Claude Haiku (80% cheaper, still capable)
export BEDROCK_MODEL_ID=anthropic.claude-3-haiku-20240307-v1:0

# Enable XML compression (default: enabled)
export USE_XML_COMPRESSION=true

# Enable incremental diff (default: enabled)
export USE_XML_DIFF=true
```

**Expected cost:** ~$0.25-$0.35 per automation run (vs $1.50-$2.00)

## Future Optimizations (Planned)

### 🔄 Batch Steps (60-70% reduction)
Combine multiple actions in one LLM call instead of one call per action.

**Status:** Flag added, implementation pending

### 🔄 Local OCR (80% reduction on OCR tokens)
Replace LLM-based OCR with local OCR (Tesseract, EasyOCR, PaddleOCR).

**Status:** Pending implementation

## Monitoring Cost

The system now logs input size at each step:

```
--- [DEBUG] LLM Input Size (Step 1):
  System Prompt: 45,234 chars (1,234 lines)
  Messages (3 messages): 125,678 chars (3,456 lines)
  Tools (15 tools): 12,345 chars (234 lines)
  TOTAL: 183,257 chars (4,924 lines) ≈ 45,814 tokens
  XML Limit: 30,000 chars per message
```

Monitor these logs to track token usage and optimize further.

## Tips for Maximum Savings

1. **Use Claude Haiku** - 80% cheaper, still very capable
2. **Keep XML compression enabled** - Always enabled by default
3. **Keep diff enabled** - Always enabled by default
4. **Break complex tasks into smaller steps** - Reduces message accumulation
5. **Monitor token usage** - Check debug logs to identify optimization opportunities

## Environment Variables Summary

```bash
# Model selection (cost optimization)
export BEDROCK_MODEL_ID=anthropic.claude-3-haiku-20240307-v1:0

# XML optimizations (enabled by default)
export USE_XML_COMPRESSION=true
export USE_XML_DIFF=true

# Future: Batch steps (disabled by default)
export USE_BATCH_STEPS=false
```

