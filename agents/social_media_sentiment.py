# agents/sentiment_agent.py
import torch
import praw
from transformers import AutoTokenizer, AutoModelForSequenceClassification


class SentimentAgent:
    def __init__(self, reddit_client_id: str, reddit_client_secret: str, reddit_user_agent: str):
        """
        Sentiment agent that scrapes Reddit discussions and analyzes sentiment
        using FinBERT.
        """
        # Initialize Reddit API
        self.reddit = praw.Reddit(
            client_id=reddit_client_id,
            client_secret=reddit_client_secret,
            user_agent=reddit_user_agent,
        )

        # Load FinBERT (financial sentiment model)
        self.tokenizer = AutoTokenizer.from_pretrained("ProsusAI/finbert")
        self.model = AutoModelForSequenceClassification.from_pretrained("ProsusAI/finbert")

    def analyze_text(self, text: str) -> str:
        """Run FinBERT sentiment classification on a text string."""
        inputs = self.tokenizer(text, return_tensors="pt", truncation=True)
        outputs = self.model(**inputs)
        scores = torch.softmax(outputs.logits, dim=1)
        labels = ["Negative", "Neutral", "Positive"]
        return labels[scores.argmax().item()]

    def analyze(self, ticker: str) -> dict:
        """Fetch Reddit posts about the ticker and compute sentiment summary."""
        mentions = []
        for submission in self.reddit.subreddit("stocks+wallstreetbets+investing").search(ticker, limit=50):
            mentions.append(submission.title + " " + submission.selftext)

        if not mentions:
            return {"Message": "No Reddit mentions"}

        sentiments = [self.analyze_text(m) for m in mentions]

        pos = sentiments.count("Positive")
        neg = sentiments.count("Negative")
        neu = sentiments.count("Neutral")

        # Interpret results
        if pos > neg:
            overall = "Bullish"
        elif neg > pos:
            overall = "Bearish"
        else:
            overall = "Neutral"

        return {
            "Reddit Mentions": len(mentions),
            "Sentiment Breakdown": f"{pos} Positive / {neg} Negative / {neu} Neutral",
            "Overall": overall,
        }


# Example usage
if __name__ == "__main__":
    # Replace with real creds or inject from Orchestrator
    agent = SentimentAgent(
        reddit_client_id="YOUR_ID",
        reddit_client_secret="YOUR_SECRET",
        reddit_user_agent="YOUR_APP"
    )
    print(agent.analyze("AAPL"))
