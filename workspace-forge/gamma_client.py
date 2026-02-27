import requests
import time
from datetime import datetime, timedelta
import os

class GammaClient:
    def __init__(self):
        self.gamma_url = "https://gamma-api.polymarket.com"
        self.markets_endpoint = f"{self.gamma_url}/markets"
        self.session = requests.Session()
        # Set a reasonable timeout
        self.session.timeout = 10
        
    def get_active_markets(self, category="crypto", active=True, max_resolution_minutes=20):
        """
        Get active crypto markets with resolution within max_resolution_minutes
        
        Args:
            category (str): Market category (default: "crypto")
            active (bool): Whether to filter for active markets
            max_resolution_minutes (int): Maximum minutes until market resolution
            
        Returns:
            list: List of market dictionaries
        """
        try:
            params = {
                "category": category,
                "active": str(active).lower()
            }
            
            response = self.session.get(self.markets_endpoint, params=params)
            response.raise_for_status()
            
            markets = response.json()
            
            # Filter markets
            filtered_markets = []
            now = datetime.now()
            max_resolution = timedelta(minutes=max_resolution_minutes)
            
            for market in markets:
                try:
                    # Parse end date
                    end_date_str = market.get("endDate")
                    if not end_date_str:
                        continue
                        
                    end_date = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
                    
                    # Skip markets that have already resolved
                    if end_date <= now:
                        continue
                        
                    # Calculate time to resolution
                    time_to_resolution = end_date - now
                    
                    # Only include markets with resolution within max_resolution_minutes
                    if time_to_resolution <= max_resolution:
                        token_ids = market.get("tokenIds", [])
                        if len(token_ids) >= 2:
                            # Get YES and NO token IDs (assume first two are YES/NO)
                            yes_token_id = token_ids[0]
                            no_token_id = token_ids[1]
                            
                            filtered_markets.append({
                                "market_id": market.get("id"),
                                "token_ids": {
                                    "yes": yes_token_id,
                                    "no": no_token_id
                                },
                                "current_price": market.get("price"),
                                "volume": market.get("volume"),
                                "end_date": end_date_str,
                                "resolution_time": time_to_resolution.total_seconds(),
                                "title": market.get("title")
                            })
                except (ValueError, KeyError) as e:
                    # Skip markets with parsing errors
                    continue
                    
            return filtered_markets
            
        except requests.exceptions.RequestException as e:
            print(f"Error fetching markets from Gamma API: {e}")
            return []
        except Exception as e:
            print(f"Unexpected error: {e}")
            return []

# Example usage
if __name__ == "__main__":
    gamma_client = GammaClient()
    markets = gamma_client.get_active_markets()
    print(f"Found {len(markets)} markets")
    for market in markets[:5]:  # Show first 5
        print(market)