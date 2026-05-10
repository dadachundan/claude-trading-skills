--- Description: "Analyzes 18-month scenarios from news headlines. Generates a comprehensive report in Japanese including primary/secondary/tertiary impacts, recommended stocks, and second opinions."
Argument-hint: "<headline>"
---

# Scenario Analyzer

Analyzes 18-month scenarios from news headlines and evaluates their impact on sectors and stocks.

## Arguments
```
$ARGUMENTS
```
**Argument Interpretation**:
- If a headline is included: The headline will be included in the analysis.
- If the argument is empty: The user will be prompted to enter a headline.

**Usage Examples**:
- `/scenario-analyzer Fed raises rates by 50bp` → Analyzes the Fed interest rate hike scenario.
- `/scenario-analyzer China announces new tariffs on US semiconductors` → Analyzes the tariff scenario.
- `/scenario-analyzer OPEC+ agrees to cut oil production` → Analyzes the oil production cut scenario.
- `/scenario-analyzer` → Prompts for headline input before analysis.

## Analysis Content

| Item | Description |
|------|------|
| **Related News** | Collects related articles from the past two weeks using WebSearch |
| **Scenario** | Three scenarios (Base/Bull/Bear) with probabilities |
| **Impact Analysis** | Primary, Secondary, and Tertiary Sector Impacts |
| **Stock Selection** | 3-5 Positive/Negative Stocks (US Market) |
| **Review** | Second Opinion (Identifying Oversights and Biases) |

## Execution Procedure

1. **Headline Analysis**:
- Extract headlines from arguments
- Prompt user input if arguments are empty
- Classify event types (Financial Policy/Geopolitics/Regulation/Technology/Commodities/Companies)

2. **Reference Reading**:
```
Read skills/scenario-analyzer/references/headline_event_patterns.md
Read skills/scenario-analyzer/references/sector_sensitivity_matrix.md
Read skills/scenario-analyzer/references/scenario_playbooks.md
```
3. **Main Analysis (scenario-analyst Agent)**:
```
Agent Tool:
- subagent_type: "scenario-analyst"
- prompt: Headline + Event Type + Reference Information
``
Output:
- List of Related News Articles
- 3 Scenarios (Base/Bull/Bear)
- Sector Impact Analysis (1st/2nd/3rd)
- Stock Recommendation List

4. **Second Opinion (strategy-reviewer agent)**:
``
Agent tool:
- subagent_type: "strategy-reviewer"
- prompt: Full Analysis Results from Step 3
``
Output:
- Identification of Oversights
- Opinion on Scenario Probability
- Bias Detection
- Suggestion of Alternative Scenarios

5. **Report Generation**:
- Integrate Results from Both Agents
- Add Final Investment Decision
- Save to `reports/scenario_analysis_<topic>_YYYYMMDD.md`
## Reference Resources
- `skills/scenario-analyzer/references/headline_event_patterns.md` - Event Patterns
- `skills/scenario-analyzer/references/sector_sensitivity_matrix.md` - Sector Sensitivity
- `skills/scenario-analyzer/references/scenario_playbooks.md` - Scenario Templates

## Important Instructions

- **Language**: All analysis and output will be in **Japanese**
- **Target Market**: Stock selection is limited to **US-listed stocks**
- **Timeframe**: Scenarios cover **18 months**
- **Probability**: Base + Bull + Bear = **100%**
- **Second Opinion**: **Required** to perform (always call strategy-reviewer)

## Output

Finally, generate a `Headline Scenario Analysis Report`, including:
- Related News Articles
- Outline of Assumed Scenario (Up to 18 Months Later)
- Impact on Sectors and Industries (Primary/Secondary/Third-Round)
- Stocks with Positive Impact (3-5 Stocks)
- Stocks with Negative Impact (3-5 Stocks)
- Second Opinion Review
- Final Investment Decision and Implications