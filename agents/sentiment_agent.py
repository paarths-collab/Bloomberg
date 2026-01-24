import os
import asyncpraw
from typing import List, Dict

class SentimentAgent:
    """Async Sentiment Analysis Agent using Reddit"""
    
    def __init__(self):
        self.reddit = None
        
    async def _init_reddit(self):
        if not self.reddit:
            self.reddit = asyncpraw.Reddit(
                client_id=os.getenv("REDDIT_CLIENT_ID"),
                client_secret=os.getenv("REDDIT_CLIENT_SECRET"),
                user_agent=os.getenv("REDDIT_USER_AGENT", "wealth_manager_v1")
            )
    
    async def analyze_batch(self, queries: List[str]) -> List[str]:
        """Simple sentiment mocking for batch queries (since Reddit text analysis is complex without NLP model)"""
        # In a real app, this would use NLTK/TextBlob on the fetched text.
        # Here we just fetch titles to prove connectivity and return them as 'context'
        results = []
        try:
            await self._init_reddit()
            # Just fetching top posts for first query as sample
            if queries:
                subreddit = await self.reddit.subreddit("investing")
                async for submission in subreddit.search(queries[0], limit=3):
                    results.append(f"Reddit: {submission.title} (Score: {submission.score})")
        except Exception as e:
            print(f"⚠️ Reddit Sentiment Error: {e}")
            results.append("Sentiment analysis unavailable")
            
        return results

    async def get_ticker_sentiment(self, ticker: str) -> float:
        """Get 0-100 sentiment score for a ticker"""
        try:
            await self._init_reddit()
            score = 0
            count = 0
            for sub in ['stocks', 'investing', 'wallstreetbets']:
                subreddit = await self.reddit.subreddit(sub)
                async for post in subreddit.search(ticker, time_filter='week', limit=10):
                    score += post.score
                    count += 1
            
            # Normalize score (arbitrary heuristic)
            if count == 0: return 50.0
            avg_score = score / count
            normalized = min(max(avg_score, 0), 100) # Cap at 100
            return normalized
        except Exception as e:
            print(f"⚠️ Ticker Sentiment Error: {e}")
            return 50.0 # Neutral default
            
    async def close(self):
        if self.reddit:
            await self.reddit.close()
