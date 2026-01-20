# Claude 4.5 Upgrade Plan

## 🚨 Urgent: Haiku 3.5 Retirement Notice

**Deadline:** February 19, 2026 @ 9:00 AM PT
**Current Model:** `claude-3-5-haiku-20241022` (retiring)
**Action Required:** Upgrade to Claude 4.x model before deadline to avoid service interruption

---

## 📊 Cost Impact Analysis

### Current Daily Usage Estimate
Based on latest workflow results (51 items matched/day):

- **Input tokens:** 91,800 (~0.092 MTok/day)
- **Output tokens:** 10,200 (~0.010 MTok/day)
- **Total:** ~0.102 MTok/day

### Cost Comparison

| Model | Input | Output | Daily | Monthly | Yearly | vs Haiku |
|-------|-------|--------|-------|---------|--------|----------|
| **Haiku 3.5** (retiring) | $1.00 | $5.00 | $0.14 | $4.28 | $52.12 | baseline |
| **Sonnet 4.5** ⭐ (recommended) | $3.00 | $15.00 | $0.43 | $12.85 | $156.37 | **+200%** |
| **Opus 4** (premium) | $15.00 | $75.00 | $2.14 | $64.26 | $781.83 | +1400% |

### 💰 Bottom Line

**Recommended upgrade to Claude 4.5 Sonnet will cost an additional ~$8.50/month or ~$104/year**

This is still very affordable for daily automated monitoring with AI-powered semantic matching.

---

## ✅ Recommended Upgrade: Claude 4.5 Sonnet

**Model ID:** `claude-sonnet-4-5-20250929`

### Why Sonnet over Opus?

1. **Cost-effective:** 3x more expensive than Haiku, but 5x cheaper than Opus
2. **Performance:** Excellent for semantic matching and JSON extraction
3. **Speed:** Faster than Opus (important for 30-min workflow timeout)
4. **Proven:** Widely used for production workloads

### Why NOT Haiku 4.x?

Claude 4.5 Haiku **does not exist yet**. Anthropic has not released a Haiku variant in the Claude 4 family. Your only options are Sonnet or Opus.

---

## 📋 Upgrade Steps

### Step 1: Update Model Configuration (5 min)

**File:** `src/matching.py` (line 41)

```python
# BEFORE (retiring)
model: str = "claude-3-5-haiku-20241022",

# AFTER (Claude 4.5 Sonnet)
model: str = "claude-sonnet-4-5-20250929",
```

### Step 2: Update Documentation (2 min)

**File:** `.claude/development-workflow.md` (line 138)

```markdown
# BEFORE
- **API Model**: Claude 3.5 Haiku (cost-optimized)

# AFTER
- **API Model**: Claude 4.5 Sonnet (balanced performance & cost)
```

### Step 3: Test Locally (10 min)

```bash
# Run with a short timeout to test the new model
export MAX_RUNTIME_MINUTES=1
python -m src.main --skip-scraping --log-level INFO

# Check that matching completes without errors
# Look for successful API calls in logs
```

### Step 4: Commit and Push

```bash
git add src/matching.py .claude/development-workflow.md
git commit -m "Upgrade to Claude 4.5 Sonnet (Haiku 3.5 retiring Feb 19)"
git push origin main
```

### Step 5: Monitor First Automated Run

- Check GitHub Actions logs after next scheduled run
- Verify matching still works correctly
- Monitor for any API errors
- Check that results quality is maintained (should actually improve!)

---

## 🔍 Testing Checklist

After upgrading, verify:

- [ ] Semantic matching completes successfully
- [ ] JSON parsing works (Sonnet is actually better at structured output)
- [ ] Match quality is maintained or improved
- [ ] No API authentication errors
- [ ] Workflow completes within 30-minute timeout
- [ ] LATEST_RESULTS.md is generated correctly
- [ ] Cost tracking in Anthropic console shows expected usage

---

## 🎯 Expected Benefits of Claude 4.5 Sonnet

While the cost increases, you'll get:

1. **Better matching accuracy** - Improved reasoning about item relevance
2. **Better JSON reliability** - Sonnet excels at structured outputs
3. **Improved vision analysis** - Better understanding of product images
4. **Future-proof** - Latest model with ongoing support
5. **Extended context** - 200K context window (vs Haiku's 200K)

---

## ⚠️ Potential Issues & Mitigation

### Issue 1: Workflow Timeout
**Risk:** Sonnet is slightly slower than Haiku
**Mitigation:** Already using 28-min timeout with 2-min buffer. Should still fit comfortably.
**Action if needed:** Reduce `max_items_per_search` from 12 to 10 in main.py

### Issue 2: Cost Overrun
**Risk:** If matching volume increases significantly
**Mitigation:** Monitor Anthropic usage dashboard
**Action if needed:**
- Reduce number of images sent per item (currently 3)
- Increase relevance threshold to reduce items evaluated
- Implement caching for previously evaluated items

### Issue 3: API Rate Limits
**Risk:** Sonnet may have different rate limits
**Mitigation:** Already using batch processing with delays
**Action if needed:** Increase delay between batches in matching.py

---

## 📅 Timeline

**Recommended completion:** Before February 10, 2026 (9 days buffer before deadline)

| Date | Action |
|------|--------|
| **Jan 20** | Read upgrade plan, understand costs |
| **Jan 21-22** | Make code changes, test locally |
| **Jan 23** | Deploy to production, monitor first run |
| **Jan 24-26** | Monitor several runs, verify stability |
| **Feb 10** | Final confirmation before deadline |

---

## 🆘 Rollback Plan

If issues arise after upgrading:

1. **Immediate rollback** (use until Feb 19):
   ```python
   model: str = "claude-3-5-haiku-20241022"
   ```

2. **Investigate issue** - Check logs, test locally

3. **Try alternative:** Claude 4 Opus (faster, more accurate, but expensive)
   ```python
   model: str = "claude-opus-4-20250514"
   ```

4. **Contact Anthropic support** if persistent issues

---

## 📞 Support Resources

- **Anthropic Model Docs:** https://docs.anthropic.com/en/docs/about-claude/models
- **Migration Guide:** https://docs.anthropic.com/en/docs/about-claude/model-migration
- **Pricing:** https://www.anthropic.com/pricing
- **API Status:** https://status.anthropic.com/

---

## ✅ Quick Start Command

To upgrade right now:

```bash
# 1. Update the model
sed -i 's/claude-3-5-haiku-20241022/claude-sonnet-4-5-20250929/g' src/matching.py

# 2. Update docs
sed -i 's/Claude 3.5 Haiku (cost-optimized)/Claude 4.5 Sonnet (balanced performance \& cost)/g' .claude/development-workflow.md

# 3. Commit
git add src/matching.py .claude/development-workflow.md
git commit -m "Upgrade to Claude 4.5 Sonnet (Haiku 3.5 retiring Feb 19, 2026)"
git push origin main

# 4. Test
python -m src.main --skip-scraping --log-level INFO
```

---

## 📈 Cost Tracking

After upgrading, monitor actual costs at:
https://console.anthropic.com/settings/usage

Compare against these estimates:
- Expected daily: $0.43
- Expected monthly: $12.85

If actual costs are significantly higher, investigate:
1. Number of items being matched daily
2. Number of images being sent per item
3. Prompt token count (may have increased)
