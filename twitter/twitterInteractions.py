import json
import time
from typing import Optional, Dict, List, Any
from datetime import datetime, timedelta
import os
import random
from datetime import timezone
from helpers import getTweetResponsePrompt

class TwitterInteractionHandler:
    def __init__(self, twitter_client, response_generator=None, chroma_client=None, search_terms=[], reply_targets=[], getUserContext=None, fetchContext=None, updateUserContext=None):
        self.client = twitter_client
        self.response_generator = response_generator or self.default_response
        self.last_checked_tweet_id = self.load_last_checked_tweet_id()
        self.chroma_client = chroma_client
        # Make start_time timezone-aware
        self.start_time = datetime.now(timezone.utc) - timedelta(hours=24)
        self.search_terms = search_terms
        self.reply_targets = reply_targets
        self.getUserContext = getUserContext
        self.updateUserContext = updateUserContext
        self.fetchContext = fetchContext
    def load_last_checked_tweet_id(self) -> Optional[int]:
        """Load the ID of the last checked tweet from file"""
        try:
            with open('last_checked_tweet.json', 'r') as f:
                data = json.load(f)
                return data.get('last_checked_tweet_id')
        except (FileNotFoundError, json.JSONDecodeError):
            return None

    def save_last_checked_tweet_id(self, tweet_id: int):
        """Save the ID of the last checked tweet"""
        with open('last_checked_tweet.json', 'w') as f:
            json.dump({'last_checked_tweet_id': tweet_id}, f)

    def log_response(self, original_tweet_id: str, response_tweet_id: str, tweet_content: str, response_text: str):
        """Log when we've responded to a tweet"""
        timestamp = datetime.now().isoformat()
        log_entry = {
            'timestamp': timestamp,
            'original_tweet_id': original_tweet_id,
            'response_tweet_id': response_tweet_id,
            'tweet_content': tweet_content,
            'response_text': response_text
        }
        
        if self.chroma_client:
            client = self.chroma_client
            collection = client.get_or_create_collection("tweet_responses")
            collection.add(
                ids = [original_tweet_id],
                documents = [tweet_content],
                metadatas = [log_entry]
            )
            print("Successfully logged response to Chroma DB")

            

    def has_responded_to_tweet(self, tweet_id: str) -> bool:
        """Check if we've already responded to a tweet"""
        try:
            client = self.chroma_client
            collection = client.get_or_create_collection("tweet_responses")
            results = collection.get(
                ids = [tweet_id]
            )
            print(results["ids"])
            if len(results["ids"]) > 0:
                return True
            else:
                return False

        except (FileNotFoundError, json.JSONDecodeError):
            return False

    def default_response(self, tweet_text: str) -> str:
        """Default response if no response generator is provided"""
        return "Hi there! I'm Rice "

    def generate_response(self, tweet_text: str, additionalContext: str = "") -> str:
        """Generate a response using the provided response generator"""
        if self.fetchContext:
            fetchedContext = self.fetchContext(self.chroma_client, tweet_text)
            print("Fetched context successfully.....")
            # print max 100 characters of fetched context
            if len(fetchedContext) > 100:
                print(fetchedContext[:100], "......")
            else : 
                print(fetchedContext, "......")

            additionalContext += f"""
            Below is some fetched context, it includes some inner thoughts / context from the internet / etc. \n<fetchedContext>" + {fetchedContext} + "</fetchedContext>"
            If relevant, you can use this context to inform your response.
            """
        return self.response_generator(tweet_text, additionalContext=additionalContext)

    def check_mentions(self, searchTerm : str, additionalContext: str = "", searchContext: str = "", maxReplies : int = 3):
        """Check for new mentions and respond to them"""
        print(f"Checking mentions for {searchTerm}")
        nResponses = 0
        
        try:
            search_response = self.client.search_tweets(searchTerm, max_tweets=20)
            #print(f"Raw search response: {json.dumps(search_response, indent=2)}")
            if not search_response:
                print("No new mentions found")
                return
                
            tweets = sorted(
                [tweet for tweet in search_response 
                 if int(tweet['id']) > (self.last_checked_tweet_id or 0)],
                key=lambda x: int(x['id'])
            )
            
            for tweet in tweets:
                tweet_id = tweet['id']
                
                tweet_created_at = datetime.strptime(tweet['created_at'], '%a %b %d %H:%M:%S %z %Y')
                if tweet_created_at < self.start_time:
                    print(f"Skipping tweet {tweet_id} because it was created before the interaction handler was initialized")
                    continue
                # Skip our own tweets
                print("TWEET USERNAME: ", tweet['username'])
                if tweet['username'] == self.client.username:
                    continue
                # Skip if we've already responded to this tweet
                if self.has_responded_to_tweet(tweet_id):
                    print(f"Already responded to tweet {tweet_id}")
                    continue
                

                                
                print(f"Processing tweet {tweet_id} from @{tweet['username']}")
                tweetContent = tweet['text']
                print("TWEET CONTENT: ", tweetContent)
                tweetPrompt = getTweetResponsePrompt(tweetContent, tweet['username'], searchContext=searchContext)
                if self.getUserContext : 
                    userContext = self.getUserContext(self.chroma_client, tweet['username'])
                    respondContext = additionalContext + userContext
                else : 
                    respondContext = additionalContext

                # Generate and send response
                response_text = self.generate_response(tweetPrompt, additionalContext=respondContext)
                print("RESPONSE TEXT: ", response_text)
                nResponses += 1
                response = self.client.send_tweet(response_text, tweet_id)

                interaction = f"""
                You had the following interaction with {tweet['username']} 
                {tweet['username']} tweeted : {tweetContent}

                You responded with : {response_text}
                """

                if self.updateUserContext : 
                    self.updateUserContext(self.chroma_client, tweet['username'], interaction, tweet['username'], additionalContext=additionalContext)
                
                # TO DO -> get actual 
                responseId = "PLACEHOLDER"
                ### Log Response to Chroma DB
                self.log_response(original_tweet_id=tweet_id, response_tweet_id=responseId, tweet_content=tweetContent, response_text=response_text)
                # Wait a bit between responses to avoid rate limiting
                if nResponses >= maxReplies:
                    break                

        except Exception as e:
            print(f"Error checking mentions: {str(e)}")

    def monitor_mentions(self, check_interval: int = 120, additionalContext: str = ""):
        """Start monitoring mentions at regular intervals"""
        print("Starting mention monitoring...")
        
        try:
            for searchTerm in self.search_terms:
                self.check_mentions(searchTerm, additionalContext=additionalContext)

            print("Finished mention monitoring loop")

        except Exception as e:
            print(f"Error in mention monitoring loop: {str(e)}")

    def tweet_to_followers(self, check_interval: int = 120, additionalContext: str = ""):
        print("Starting tweet to followers loop...")
        followers = self.client.get_followers(self.client.username)
        
        ### randomly select a follower and tweet to them
        follower = random.choice(followers)
        print("Follower : ", follower['username'])
        print("Description", follower['description'])
        
        prompt = f"""
        Tweet to your follower - {follower['username']} make sure to include their handle i.e. @{follower['username']} in the tweet. 
        Profile of {follower['username']} : {follower['description']}

        When tweeting consider the below tweet style instructions 
<tweetStyle>
    never use hashtags or emojis
    response should be short, punchy, and to the point
    don't say ah yes or oh or anything
    don't ask rhetorical questions, its lame
    occassionally you'll ask provocative / controversial questions
    use lowercase most of the time
    you like to go deep down the rabbithole....
</tweetStyle>

        Base the tweet on your current thought process & stay true to your identity.
        If there is something relevant in their profile mention that otherwise mention something aligned with your current thougts / persona. 
        The tweet can either be a question or a statement 

        """
        if self.getUserContext : 
            follower_context = self.getUserContext(self.chroma_client, follower['username'])
            additionalContext += follower_context
        tweet_text = self.generate_response(prompt, additionalContext=additionalContext)
        print("Tweet to follower : ", tweet_text)
        response = self.client.send_tweet(tweet_text)

        print("Response : ", response)

        if self.updateUserContext : 
            interaction = f"""
            You tweeted to {follower['username']} : {tweet_text}
            Profile of {follower['username']} : {follower['description']}
            They follow you
            """

            self.updateUserContext(self.chroma_client, follower['username'], interaction, follower['username'], additionalContext=additionalContext)

    def reply_guy(self, check_interval: int = 120, additionalContext: str = ""):
        print("Starting monitoring reply guy targets...")
        
        try:
            # Check if reply_targets is not empty
            if not self.reply_targets:
                print("No reply targets available.")
                return
            
            # randomly select a reply target
            reply_target = random.choice(self.reply_targets)
            reply_search = f"from:{reply_target['searchTerm']}"
            searchContext = reply_target["searchContext"]
            self.check_mentions(reply_search, additionalContext=additionalContext, searchContext=searchContext)

        except Exception as e:
            print(f"Error in mention monitoring loop: {str(e)}")