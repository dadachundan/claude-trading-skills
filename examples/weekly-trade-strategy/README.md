# Weekly Trade Strategy Blog Generator

An AI agent system that automatically generates weekly trading strategy blogs for US stocks.

[English](#english) | [Japanese](#japanese)

---

## <a name="japanese"></a>Japanese

### Overview

This project utilizes Claude Agents to automatically generate weekly trading strategy blogs for the US stock market. It performs chart analysis, market environment assessment, and news analysis step-by-step to generate practical strategy reports for part-time traders.


### Main Features

- **Technical Analysis**: Weekly chart analysis of VIX, interest rates, Breadth indicator, major indices, and commodities
- **Market Environment Assessment**: Bubble risk detection, sentiment analysis, sector rotation analysis
- **News & Event Analysis**: Impact assessment of news over the past 10 days, economic indicators and earnings forecasts for the next 7 days
- **Weekly Strategy Blog Generation**: Integrates three analysis reports and outputs a practical trading strategy in 200-300 lines of Markdown format
- **Medium- to Long-Term Strategy Report** (Optional): Generates a Druckenmiller-style 18-month investment strategy in 4 scenarios (Base/Bull/Bear/Tail Risk)

### Prerequisites

- **Claude Code CLI** or **Claude Desktop**
- The following Claude skills must be available:
- `technical-analyst`
- `breadth-chart-analyst`
- `sector-analyst`
- `market-environment-analysis`
- `us-market-bubble-detector`
- `market-news-analyst`
- `economic-calendar-fetcher`
- `earnings-calendar`
- `stanley-druckenmiller-investment` (for medium- to long-term strategies)

### Setup

1. **Clone the repository**

```bash
git clone <repository-url>
cd weekly-trade-strategy
```
2. **Set environment variables**

Create a `.env` file and set the required API key:

```bash
# Financial Modeling Prep API (for obtaining financial statements and economic calendars)
FMP_API_KEY=your_api_key_here
```
3. **Check the folder structure**

```
weekly-trade-strategy/
├── charts/ # Chart Image Storage Folder
├── reports/ # Analysis Report Storage Folder
├── blogs/ # Final Blog Post Storage Folder
├── skills/ # Claude Skill Definitions
└── .claude/
└── agents/ # Claude Agent Definitions
```
### How to Use
#### Quick Start
1. **Prepare Chart Images** (18 recommended)
```bash
# Create a date folder
mkdir -p charts/2025-11-03
# Place Chart Images (The following images are recommended)
# - VIX (Weekly)
# - US 10-Year Treasury Yield (Weekly)
# - S&P 500 Breadth Index
# - Nasdaq 100, S&P 500, Russell 2000, Dow (Weekly)
# - Gold, Copper, Crude Oil, Natural Gas, Uranium (Weekly)
# - Uptrend Stock Ratio
# - Sector/Industry Performance
# - Earnings Calendar, Heatmap
```
2. **Create a Reports Folder**

```bash
mkdir -p reports/2025-11-03
```
3. **Batch Execution Prompt** (Execute in Claude Code/Desktop)

```
Create a trading strategy blog for the week of 2025-11-03.

1. Analyze all charts at charts/2025-11-03/ using technical-market-analyst

→ reports/2025-11-03/technical-market-analysis.md

2. Conduct a comprehensive market environment assessment using us-market-analyst

→ reports/2025-11-03/us-market-analysis.md

3. Analyze news/events using market-news-analyzer

→ reports/2025-11-03/market-news-analysis.md

4. Generate the final blog post using weekly-trade-blog-writer

→ blogs/2025-11-03-weekly-strategy.md

Perform each step sequentially, review the report, and then proceed.
```

4. **Optional: Generate Medium- to Long-Term Strategy Report**

In addition to the weekly blog, you can generate an 18-month medium- to long-term investment strategy report (quarterly recommended).

```
Develop an 18-month strategy as of November 3, 2025, using the druckenmiller-strategy-planner agent.

Comprehensively analyze the three reports under reports/2025-11-03/,
apply the Druckenmiller strategic framework, and save it to reports/2025-11-03/druckenmiller-strategy.md.
```
**Features**:
- 18-month leading medium- to long-term macroeconomic analysis
- Four scenarios (Base/Bull/Bear/Tail Risk) and probability assessments
- Position sizing recommendations based on confidence level
- Identification of macroeconomic turning points (monetary policy, business cycle)
- Clearly define invalidation conditions for each scenario

#### Step-by-Step Execution

For more detailed instructions, please refer to `CLAUDE.md`.

### Project Structure
```
weekly-trade-strategy/
│
├── charts/ # Chart Images
│ └── YYYY-MM-DD/
│ ├── vix.jpeg
│ ├── 10year_yield.jpeg
│ └── ...
│
├── reports/ # Analysis Reports
│ └── YYYY-MM-DD/
│ ├── technical-market-analysis.md
│ ├── us-market-analysis.md
│ ├── market-news-analysis.md
│ └── druckenmiller-strategy.md # (Option: Medium- to Long-Term Strategy)
│
├── blogs/ # Final Blog Post
│ └── YYYY-MM-DD-weekly-strategy.md
│
├── skills/ # Claude Skill Definitions
│ ├── technical-analyst/
│ ├── breadth-chart-analyst/
│ ├── sector-analyst/
│ ├── market-news-analyst/
│ ├── us-market-bubble-detector/
│ └── ...
│
├── .claude/
│ └── agents/ # Claude Agent Definitions
│ ├── technical-market-analyst.md
│ ├── us-market-analyst.md
│ ├── market-news-analyzer.md
│ ├── weekly-trade-blog-writer.md
│ └── druckenmiller-strategy-planner.md # (Optional: Medium- to Long-Term Strategy)
│
├── CLAUDE.md # Detailed Execution Guide
├── README.md # This file
├── .env # Environment variables (must be created)
└── .gitignore
```
### Agent List
| Agent | Role | Output |
|---------|------|------|
| `technical-market-analyst` | Perform technical analysis from chart images | `technical-market-analysis.md` |
| `us-market-analyst` | Evaluate market conditions and bubble risks | `us-market-analysis.md` |
| `market-news-analyzer` | Analyze news impact and event forecasts | `market-news-analysis.md` |
| `weekly-trade-blog-writer` | Integrate three reports to generate a blog post | `YYYY-MM-DD-weekly-strategy.md` |
| `druckenmiller-strategy-planner` (Optional) | Medium- to Long-Term (18-Month) Strategy Planning (4-Scenario Analysis) | `druckenmiller-strategy.md` |

### Troubleshooting

**Q: Agent cannot find charts**
- Verify that the `charts/YYYY-MM-DD/` folder exists
- Verify that the image format is `.jpeg` or `.png`

**Q: Report not generated**
- Verify that the `reports/YYYY-MM-DD/` folder has been created
- Verify that the report from the previous step was generated successfully

**Q: Blog post sector allocation is changing abruptly**
- Verify that the previous week's blog post exists in the `blogs/` directory
- The agent is designed to make gradual adjustments (±10-15%)

**Q: FMP API error occurs**
- Ensure `FMP_API_KEY` is present in the `.env` file Verify that it is set up correctly
- Verify the validity of the API key ([Financial Modeling Prep](https://site.financialmodelingprep.com/))

### License

This project is released under the MIT License.

### Contributions

Pull requests are welcome. For major changes, please open an issue first to discuss the changes.

--

## <a name="english"></a>English

### Overview

An AI ag