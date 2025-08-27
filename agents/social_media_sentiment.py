import praw

reddit = praw.Reddit(
    client_id="YOUR_CLIENT_ID",
    client_secret="YOUR_SECRET",
    user_agent="quant-insights-agent"
)

subreddit = reddit.subreddit("wallstreetbets")
for post in subreddit.hot(limit=5):
    print(post.title)
