import os
from typing import Dict,List,Tuple,Any
import pandas as pd
import streamlit as st
import plotly.express as px 
# --- Attempt to import optional dependencies ---
try:
    import torch
    import praw
    from transformers import AutoTokenizer, AutoModelForSequenceClassification
    _HAS_DEPS = True
except ImportError:
    _HAS_DEPS = False

class SentimentAgent:
    """
    Analyzes social media sentiment from Reddit using FinBERT.
    """

    def __init__(self, reddit_client_id: str, reddit_client_secret: str, reddit_user_agent: str):
        # --- Check dependencies ---
        if not _HAS_DEPS:
            self.reddit = None
            self.tokenizer = None
            self.model = None
            print("[ERROR] SentimentAgent: Missing dependencies (praw, torch, transformers).")
            return

        # --- Check credentials ---
        if not all([reddit_client_id, reddit_client_secret, reddit_user_agent]):
            self.reddit = None
            print("[WARNING] SentimentAgent: Reddit credentials missing. Agent disabled.")
            return

        # --- Initialize Reddit client & FinBERT model ---
        try:
            self.reddit = praw.Reddit(
                client_id=reddit_client_id,
                client_secret=reddit_client_secret,
                user_agent=reddit_user_agent,
                read_only=True
            )
            self.tokenizer = AutoTokenizer.from_pretrained("ProsusAI/finbert")
            self.model = AutoModelForSequenceClassification.from_pretrained("ProsusAI/finbert")
            print("[SUCCESS] SentimentAgent: Initialized successfully.")
        except Exception as e:
            self.reddit = None
            print(f"[ERROR] SentimentAgent: Initialization failed: {e}")

    def _analyze_text(self, text: str) -> str:
        """
        Run FinBERT sentiment classification on a text string.
        Returns one of: "positive", "negative", "neutral"
        """
        inputs = self.tokenizer(text, return_tensors="pt", truncation=True, max_length=512)
        with torch.no_grad():
            outputs = self.model(**inputs)
        scores = torch.softmax(outputs.logits, dim=1)
        return self.model.config.id2label[scores.argmax().item()]

    def analyze(self, ticker: str) -> Dict[str, Any]:
        """
        Fetch Reddit posts about the ticker and compute sentiment summary.
        """
        if not self.reddit:
            return {"Error": "SentimentAgent is not properly initialized."}

        print(f"SentimentAgent: Searching Reddit for '{ticker}'...")
        try:
            mentions = [
                post.title for post in self.reddit.subreddit("stocks+wallstreetbets+investing")
                .search(ticker, limit=25)
            ]

            if not mentions:
                return {"Message": f"No recent Reddit mentions found for '{ticker}'."}

            sentiments = [self._analyze_text(text) for text in mentions]

            pos = sentiments.count("positive")
            neg = sentiments.count("negative")
            neu = sentiments.count("neutral")

            # Overall sentiment logic
            if pos > neg * 1.5:
                overall = "Bullish"
            elif neg > pos * 1.5:
                overall = "Bearish"
            else:
                overall = "Neutral"

            return {
                "Reddit Mentions Analyzed": len(mentions),
                "Positive": pos,
                "Negative": neg,
                "Neutral": neu,
                "Overall Social Sentiment": overall
            }

        except Exception as e:
            return {"Error": f"Failed to analyze Reddit sentiment for {ticker}: {e}"}


# --- Streamlit visualization ---
if __name__ == "__main__":
    st.set_page_config(page_title="Social Media Sentiment", layout="wide")
    st.title("💬 Social Media Sentiment Agent (Reddit + FinBERT)")

    # --- Load Reddit credentials ---
    REDDIT_ID = st.secrets.get("REDDIT_CLIENT_ID", os.getenv("REDDIT_CLIENT_ID"))
    REDDIT_SECRET = st.secrets.get("REDDIT_CLIENT_SECRET", os.getenv("REDDIT_CLIENT_SECRET"))
    REDDIT_AGENT = st.secrets.get("REDDIT_USER_AGENT", os.getenv("REDDIT_USER_AGENT"))

    if not all([REDDIT_ID, REDDIT_SECRET, REDDIT_AGENT]):
        st.error("Reddit API credentials not found! Please set them in Streamlit secrets.")
    else:
        agent = SentimentAgent(
            reddit_client_id=REDDIT_ID,
            reddit_client_secret=REDDIT_SECRET,
            reddit_user_agent=REDDIT_AGENT
        )

        with st.sidebar:
            st.header("⚙️ Configuration")
            ticker = st.text_input("Ticker Symbol", "NVDA")
            run_button = st.button("🔬 Analyze Sentiment", use_container_width=True)

        if run_button:
            st.header(f"Results for {ticker}")
            with st.spinner(f"Scraping Reddit and running FinBERT analysis for {ticker}..."):
                results = agent.analyze(ticker)

                if "Error" in results:
                    st.error(results["Error"])
                elif "Message" in results:
                    st.warning(results["Message"])
                else:
                    st.subheader("Sentiment Summary")
                    cols = st.columns(4)
                    cols[0].metric("Overall Sentiment", results.get("Overall Social Sentiment", "N/A"))
                    cols[1].metric("Positive Mentions 👍", results.get("Positive", 0))
                    cols[2].metric("Negative Mentions 👎", results.get("Negative", 0))
                    cols[3].metric("Neutral Mentions 😐", results.get("Neutral", 0))

                    # Pie chart
                    df_counts = pd.DataFrame({
                        "Sentiment": ["Positive", "Negative", "Neutral"],
                        "Count": [results.get("Positive", 0), results.get("Negative", 0), results.get("Neutral", 0)]
                    })
                    fig = px.pie(df_counts, names="Sentiment", values="Count",
                                 color="Sentiment",
                                 color_discrete_map={"Positive":"green", "Negative":"red", "Neutral":"grey"},
                                 title="Breakdown of Reddit Mentions")
                    st.plotly_chart(fig, use_container_width=True)



# import streamlit as st
# import pandas as pd
# import os
# from typing import Dict

# # --- Try to import necessary libraries ---
# try:
#     import torch
#     import praw
#     from transformers import AutoTokenizer, AutoModelForSequenceClassification
#     _HAS_DEPS = True
# except ImportError:
#     _HAS_DEPS = False

# class SentimentAgent:
#     def __init__(self, reddit_client_id: str, reddit_client_secret: str, reddit_user_agent: str):
#         if not _HAS_DEPS:
#             self.reddit = None
#             self.model = None
#             self.tokenizer = None
#             print("❌ SentimentAgent ERROR: Missing dependencies (praw, torch, transformers). Agent is disabled.")
#             return

#         if not all([reddit_client_id, reddit_client_secret, reddit_user_agent]):
#             self.reddit = None
#             print("❌ SentimentAgent WARNING: Reddit credentials missing. Agent is disabled.")
#             return

#         try:
#             self.reddit = praw.Reddit(
#                 client_id=reddit_client_id, client_secret=reddit_client_secret,
#                 user_agent=reddit_user_agent, read_only=True
#             )
#             self.tokenizer = AutoTokenizer.from_pretrained("ProsusAI/finbert")
#             self.model = AutoModelForSequenceClassification.from_pretrained("ProsusAI/finbert")
#             print("✅ SentimentAgent: Initialized with Reddit API and FinBERT model.")
#         except Exception as e:
#             self.reddit = None
#             print(f"❌ SentimentAgent ERROR: Initialization failed: {e}")

#     def _analyze_text(self, text: str) -> str:
#         """Run FinBERT sentiment classification on a text string."""
#         inputs = self.tokenizer(text, return_tensors="pt", truncation=True, max_length=512)
#         with torch.no_grad():
#             outputs = self.model(**inputs)
#         scores = torch.softmax(outputs.logits, dim=1)
#         return self.model.config.id2label[scores.argmax().item()]

#     def analyze(self, ticker: str) -> dict:
#         """Fetch Reddit posts about the ticker and compute sentiment summary."""
#         if not self.reddit:
#             return {"Error": "SentimentAgent is not properly initialized."}
            
#         print(f"SentimentAgent: Searching Reddit for '{ticker}'...")
#         try:
#             mentions = [sub.title for sub in self.reddit.subreddit("stocks+wallstreetbets+investing").search(ticker, limit=25)]
#             if not mentions:
#                 return {"Message": f"No recent Reddit mentions found for '{ticker}'."}

#             sentiments = [self._analyze_text(m) for m in mentions]
#             pos = sentiments.count("positive")
#             neg = sentiments.count("negative")
#             neu = sentiments.count("neutral")

#             if pos > neg * 1.5: overall = "Bullish"
#             elif neg > pos * 1.5: overall = "Bearish"
#             else: overall = "Neutral"

#             return {
#                 "Reddit Mentions Analyzed": len(mentions),
#                 "Positive": pos, "Negative": neg, "Neutral": neu,
#                 "Overall Social Sentiment": overall,
#             }
#         except Exception as e:
#             return {"Error": f"Failed to analyze Reddit sentiment for {ticker}: {e}"}

# # --- Streamlit Visualization ---
# if __name__ == "__main__":
#     st.set_page_config(page_title="Social Media Sentiment", layout="wide")
#     st.title("💬 Social Media Sentiment Agent (Reddit + FinBERT)")
    
#     # Load credentials from secrets for standalone testing
#     REDDIT_ID = st.secrets.get("REDDIT_CLIENT_ID", os.getenv("REDDIT_CLIENT_ID"))
#     REDDIT_SECRET = st.secrets.get("REDDIT_CLIENT_SECRET", os.getenv("REDDIT_CLIENT_SECRET"))
#     REDDIT_AGENT = st.secrets.get("REDDIT_USER_AGENT", os.getenv("REDDIT_USER_AGENT"))

#     if not all([REDDIT_ID, REDDIT_SECRET, REDDIT_AGENT]):
#         st.error("Reddit API credentials not found! Please set them in your Streamlit secrets.")
#     else:
#         agent = SentimentAgent(
#             reddit_client_id=REDDIT_ID,
#             reddit_client_secret=REDDIT_SECRET,
#             reddit_user_agent=REDDIT_AGENT
#         )
#         with st.sidebar:
#             st.header("⚙️ Configuration")
#             ticker = st.text_input("Ticker Symbol", "NVDA")
#             run_button = st.button("🔬 Analyze Sentiment", use_container_width=True)

#         if run_button:
#             st.header(f"Results for {ticker}")
#             with st.spinner(f"Scraping Reddit and running FinBERT analysis for {ticker}..."):
#                 results = agent.analyze(ticker)
#                 if "Error" in results:
#                     st.error(results["Error"])
#                 elif "Message" in results:
#                     st.warning(results["Message"])
#                 else:
#                     st.subheader("Sentiment Summary")
#                     cols = st.columns(4)
#                     cols[0].metric("Overall Sentiment", results.get("Overall Social Sentiment", "N/A"))
#                     cols[1].metric("Positive Mentions 👍", results.get("Positive", 0))
#                     cols[2].metric("Negative Mentions 👎", results.get("Negative", 0))
#                     cols[3].metric("Neutral Mentions 😐", results.get("Neutral", 0))

#                     # Create a pie chart
#                     sentiment_counts = pd.DataFrame({
#                         "Sentiment": ["Positive", "Negative", "Neutral"],
#                         "Count": [results.get("Positive", 0), results.get("Negative", 0), results.get("Neutral", 0)]
#                     })
#                     fig = pd.pie(sentiment_counts, values='Count', names='Sentiment', 
#                                  title='Breakdown of Reddit Mentions',
#                                  color_discrete_map={'Positive':'green', 'Negative':'red', 'Neutral':'grey'})
#                     st.plotly_chart(fig, use_container_width=True)