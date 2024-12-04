import requests
import json
import time
from typing import Optional, Dict, List, Any
from datetime import datetime
from urllib.parse import urlencode

import chromadb

class TwitterClient:
    BASE_URL = "https://twitter.com"
    API_URL = "https://api.twitter.com"
    
    def __init__(
        self,
        username: Optional[str] = None,
        password: Optional[str] = None,
        email: Optional[str] = None,
        cookies: Optional[str] = None,
        poll_interval: int = 120,
        chroma_client: Optional[chromadb.Client] = None
    ):
        self.username = username
        self.password = password
        self.email = email
        self.poll_interval = poll_interval
        self.session = requests.Session()
        self.bearer_token = "AAAAAAAAAAAAAAAAAAAAAFQODgEAAAAAVHTp76lzh3rFzcHbmHVvQxYYpTw%3DckAlMINMjmCwxUcaXbAN4XqJVdgMJaHqNOFgPMK0zN1qLqLQCF"
        self.chroma_client = chroma_client
        
        # Set up default headers
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Authorization": f"Bearer {self.bearer_token}",
            "Content-Type": "application/json",
            "Accept": "*/*"
        })
        
        if cookies:
            self._setup_cookies(cookies)

    def _get_default_features(self) -> Dict[str, bool]:
        """Get default feature flags required by Twitter"""
        return {
            # Core features
            "verified_phone_label_enabled": False,
            "tweetypie_unmention_optimization_enabled": True,
            "responsive_web_edit_tweet_api_enabled": True,
            "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
            "view_counts_everywhere_api_enabled": True,
            "longform_notetweets_consumption_enabled": True,
            "responsive_web_twitter_article_tweet_consumption_enabled": False,
            "tweet_awards_web_tipping_enabled": False,
            "freedom_of_speech_not_reach_fetch_enabled": True,
            "standardized_nudges_misinfo": True,
            "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
            "longform_notetweets_rich_text_read_enabled": True,
            "longform_notetweets_inline_media_enabled": True,
            "responsive_web_enhance_cards_enabled": False,
            "responsive_web_graphql_exclude_directive_enabled": True,
            "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
            "responsive_web_graphql_timeline_navigation_enabled": True,
            
            # Missing required features that caused the error
            "vibe_api_enabled": False,
            "responsive_web_text_conversations_enabled": False,
            "interactive_text_enabled": True,
            "blue_business_profile_image_shape_enabled": False,
            
            # Additional features
            "c9s_tweet_anatomy_moderator_badge_enabled": True,
            "rweb_video_timestamps_enabled": True,
            "responsive_web_media_download_video_enabled": False,
            "rweb_tipjar_consumption_enabled": True,
            "articles_preview_enabled": True,
            "creator_subscriptions_quote_tweet_preview_enabled": True,
            "communities_web_enable_tweet_community_results_fetch": True,
            "android_graphql_skip_api_media_color_palette": False,
            "creator_subscriptions_tweet_preview_api_enabled": True,
            
            # Additional conversation and UI features
            "responsive_web_enhance_cards_enabled": False,
            "unified_cards_ad_metadata_container_dynamic_card_content_query_enabled": False,
            "responsive_web_twitter_article_tweet_consumption_enabled": False,
            "longform_notetweets_rich_text_read_enabled": True,
            "responsive_web_graphql_timeline_navigation_enabled": True
        }
            
    def _setup_cookies(self, cookies_str: str) -> None:
        """Set up session cookies from a cookie string"""
        try:
            cookie_list = json.loads(cookies_str)
            for cookie in cookie_list:
                self.session.cookies.set(
                    cookie["name"],
                    cookie["value"],
                    domain=cookie.get("domain", ".twitter.com"),
                    path=cookie.get("path", "/")
                )
        except json.JSONDecodeError:
            # Handle raw cookie string format
            for cookie in cookies_str.split(';'):
                if '=' in cookie:
                    name, value = cookie.strip().split('=', 1)
                    self.session.cookies.set(name, value, domain=".twitter.com", path="/")
    
    def get_csrf_token(self) -> str:
        """Get CSRF token from cookies"""
        return self.session.cookies.get("ct0", domain=".twitter.com")

    def _update_headers_with_csrf(self) -> None:
        """Update headers with CSRF token"""
        csrf_token = self.get_csrf_token()
        if csrf_token:
            self.session.headers.update({
                "x-csrf-token": csrf_token,
            })

    def search_tweets(self, query: str, max_tweets: int = 20) -> List[Dict]:
        """
        Search for tweets using Twitter's search API
        """
        self._update_headers_with_csrf()
        
        variables = {
            "rawQuery": query,
            "count": min(max_tweets, 40),
            "querySource": "typed_query",
            "product": "Latest",
            "includePromotedContent": False,
            "withDownvotePerspective": False,
            "withReactionsMetadata": False,
            "withReactionsPerspective": False
        }

        features = self._get_default_features()
        
        # Field toggles are also required for some requests
        field_toggles = {
            "withArticleRichContentState": False
        }

        params = {
            "variables": json.dumps(variables),
            "features": json.dumps(features),
            "fieldToggles": json.dumps(field_toggles)
        }

        try:
            response = self.session.get(
                f"{self.BASE_URL}/i/api/graphql/gkjsKepM6gl_HmFWoWKfgg/SearchTimeline",
                params=params
            )
            
            if response.status_code != 200:
                print(f"Search request failed: {response.text}")
                return []

            data = response.json()
            tweets = []
            
            # Navigate through the response structure
            instructions = data.get('data', {}).get('search_by_raw_query', {}).get('search_timeline', {}).get('timeline', {}).get('instructions', [])
            
            for instruction in instructions:
                if instruction.get('type') == 'TimelineAddEntries':
                    entries = instruction.get('entries', [])
                    for entry in entries:
                        if not entry.get('entryId', '').startswith('tweet-'):
                            continue
                            
                        result = entry.get('content', {}).get('itemContent', {}).get('tweet_results', {}).get('result', {})
                        if not result:
                            continue

                        legacy = result.get('legacy', {})
                        user_result = result.get('core', {}).get('user_results', {}).get('result', {})
                        user_legacy = user_result.get('legacy', {})

                        if not legacy or not user_legacy:
                            continue

                        tweet = {
                            'id': legacy.get('id_str'),
                            'text': legacy.get('full_text'),
                            'username': user_legacy.get('screen_name'),
                            'name': user_legacy.get('name'),
                            'user_id': user_legacy.get('id_str'),
                            'created_at': legacy.get('created_at'),
                            'conversation_id': legacy.get('conversation_id_str'),
                            'in_reply_to_status_id': legacy.get('in_reply_to_status_id_str'),
                            'in_reply_to_user_id': legacy.get('in_reply_to_user_id_str'),
                        }
                        
                        tweets.append(tweet)

            return tweets

        except Exception as e:
            print(f"Error during search: {str(e)}")
            return []


    def send_tweet(self, text: str, reply_to_tweet_id: Optional[str] = None) -> dict:
        """Send a tweet or reply to another tweet"""
        self._update_headers_with_csrf()
        
        # Add debug logging
        print(f"Headers: {self.session.headers}")
        print(f"Cookies: {self.session.cookies.get_dict()}")
        
        variables = {
            "tweet_text": text,
            "dark_request": False,
            "media": {
                "media_entities": [],
                "possibly_sensitive": False
            },
            "semantic_annotation_ids": []
        }

        if reply_to_tweet_id:
            variables["reply"] = {"in_reply_to_tweet_id": reply_to_tweet_id}

        payload = {
            "variables": variables,
            "features": self._get_default_features(),
            "queryId": "a1p9RWpkYKBjWv_I3WzS-A"
        }

        response = self.session.post(
            f"{self.BASE_URL}/i/api/graphql/a1p9RWpkYKBjWv_I3WzS-A/CreateTweet",
            json=payload
        )
        
        if response.status_code != 200:
            # Add more detailed error information
            print(f"Response status code: {response.status_code}")
            print(f"Response headers: {response.headers}")
            print(f"Response body: {response.text}")
            raise Exception(f"Failed to send tweet: Status {response.status_code} - {response.text}")
            
        return response.json()

    def get_tweet(self, tweet_id: str) -> dict:
        """Fetch a specific tweet by ID"""
        self._update_headers_with_csrf()
        
        variables = {
            "focalTweetId": tweet_id,
            "with_rux_injections": False,
            "includePromotedContent": False,
            "withCommunity": True,
            "withQuickPromoteEligibilityTweetFields": True,
            "withBirdwatchNotes": False,
            "withVoice": True,
            "withV2Timeline": True
        }

        params = {
            "variables": json.dumps(variables),
            "features": json.dumps(self._get_default_features())
        }

        response = self.session.get(
            f"{self.BASE_URL}/i/api/graphql/xOhkmRac04YFZmOzU9PJHg/TweetDetail",
            params=params
        )
        
        if response.status_code != 200:
            raise Exception(f"Failed to fetch tweet: {response.text}")
            
        return response.json()

    def get_user_tweets(self, user_id: str, max_tweets: int = 40) -> List[dict]:
        """Fetch tweets from a specific user"""
        self._update_headers_with_csrf()
        
        variables = {
            "userId": user_id,
            "count": min(max_tweets, 40),
            "includePromotedContent": False,
            "withQuickPromoteEligibilityTweetFields": True,
            "withVoice": True,
            "withV2Timeline": True
        }

        params = {
            "variables": json.dumps(variables),
            "features": json.dumps(self._get_default_features())
        }

        response = self.session.get(
            f"{self.BASE_URL}/i/api/graphql/V7H0Ap3_Hh2FyS75OCDO3Q/UserTweets",
            params=params
        )
        
        if response.status_code != 200:
            raise Exception(f"Failed to fetch user tweets: {response.text}")
            
        return response.json()