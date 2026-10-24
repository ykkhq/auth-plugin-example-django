# Token usage: conventional MCP vs Code Mode

Run 2026-10-16 01:03, model `sonnet`, `claude -p` (no settings/plugins/skills, no built-in tools), same system prompt and task per row. Input tokens include cache reads/writes.

| Task | Mode | Input tokens | Output tokens | Turns | Cost (USD) | Time (s) |
|---|---|---:|---:|---:|---:|---:|
| baseline | conventional | 13,886 | 4 | 1 | 0.0041 | 3.5 |
| baseline | codemode | 1,947 | 5 | 1 | 0.0017 | 2.9 |
| lookup | conventional | 28,537 | 39 | 2 | 0.0099 | 4.6 |
| lookup | codemode | 11,307 | 239 | 3 | 0.0172 | 6.7 |
| multi_step | conventional | 43,487 | 326 | 4 | 0.0172 | 6.7 |
| multi_step | codemode | 13,031 | 326 | 3 | 0.0233 | 7.7 |
| bulk | conventional | 139,400 | 4,263 | 14 | 0.3652 | 29.9 |
| bulk | codemode | 45,396 | 883 | 5 | 0.0538 | 11.3 |

## Code Mode vs conventional

Conventional → Code Mode; negative % = Code Mode uses less. Cost depends on prompt-cache hits across runs (cache reads are ~10x cheaper than writes), so token counts are the cleaner signal.

| Task | Input tokens | Output tokens | Total tokens | Cost (USD) |
|---|---:|---:|---:|---:|
| baseline | 13,886 → 1,947 (-86%) | 4 → 5 (+25%) | 13,890 → 1,952 | 0.0041 → 0.0017 (-59%) |
| lookup | 28,537 → 11,307 (-60%) | 39 → 239 (+513%) | 28,576 → 11,546 | 0.0099 → 0.0172 (+74%) |
| multi_step | 43,487 → 13,031 (-70%) | 326 → 326 (+0%) | 43,813 → 13,357 | 0.0172 → 0.0233 (+35%) |
| bulk | 139,400 → 45,396 (-67%) | 4,263 → 883 (-79%) | 143,663 → 46,279 | 0.3652 → 0.0538 (-85%) |

## Answers

| Task | Expected (REST API) | Mode | Answer |
|---|---|---|---|
| baseline | OK | conventional | OK |
| baseline | OK | codemode | OK. |
| lookup | 25 | conventional | 25 |
| lookup | 25 | codemode | 25 |
| multi_step | yes | conventional | Yes. 3 more Desk Workstation Bundles (FG-2001) can be built from current component stock, and no component is short.  / Component / Needed (3 bundles) / In stock / /---/---/---/ / 27in Monitor / 3 / 25 / / Laptop Stand / 3 / 60 / / Mechanic |
| multi_step | yes | codemode | Yes. Current stock covers 3 more FG-2001 bundles, and no component is short.  / Component / Needed for 3 / In stock / /---/---/---/ / 27in Monitor / 3 / 25 / / Laptop Stand / 3 / 60 / / Mechanical Keyboard / 3 / 40 / / USB-C Cable / 6 / 150 |
| bulk | Hiroshima Office Pro: 43 orders, 126703.51; Fukuoka Desk Center: 33 orders, 98377.67; Sendai Business Gear: 27 orders, 97261.87 | conventional | Top 3 customers by total order value, across all order statuses:  / Rank / Customer / Orders / Total value / /---/---/---/---/ / 1 / Hiroshima Office Pro / 43 / 126,703.51 / / 2 / Fukuoka Desk Center / 33 / 98,377.67 / / 3 / Sendai Business |
| bulk | Hiroshima Office Pro: 43 orders, 126703.51; Fukuoka Desk Center: 33 orders, 98377.67; Sendai Business Gear: 27 orders, 97261.87 | codemode | Across all 301 sales orders, these three customers have the highest total order value:  / Customer / Orders / Total value / /---/---/---/ / Hiroshima Office Pro / 43 / 126,703.51 / / Fukuoka Desk Center / 33 / 98,377.67 / / Sendai Business  |
