class RateLimiter {
  constructor(maxRequests, intervalMs) {
    this.maxRequests = maxRequests;
    this.intervalMs = intervalMs;
    this.requestQueue = [];
  }

  async acquire() {
    return new Promise((resolve, reject) => {
      const now = Date.now();

      // Remove requests that are outside the rate limit window
      while (this.requestQueue.length > 0 && this.requestQueue[0] <= now - this.intervalMs) {
        this.requestQueue.shift();
      }

      if (this.requestQueue.length < this.maxRequests) {
        // If we're under the limit, execute immediately
        this.requestQueue.push(now);
        resolve();
      } else {
        // Otherwise, queue the request
        const delay = this.intervalMs - (now - this.requestQueue[0]) + 1; // Ensure delay is at least 1ms
        setTimeout(() => {
          this.requestQueue.push(Date.now());
          resolve();
        }, delay);
      }
    });
  }

  async execute(fn) {
    await this.acquire();
    try {
      return await fn();
    } catch (error) {
      console.error("Error executing rate-limited function:", error);
      throw error; // Re-throw the error so the caller knows it failed
    }
  }
}

// Example Usage (Discord ping):
const rateLimiter = new RateLimiter(1, 5000); // 1 request every 5 seconds

async function pingDiscord(message) {
  try {
    // Assuming 'message' tool is globally available
    await default_api.message(action='send', channel='pulse', message=message);
    console.log("Discord ping sent successfully.");
  } catch (error) {
    console.error("Failed to send Discord ping:", error);
    throw error; // Re-throw the error to indicate failure
  }
}

async function rateLimitedPing() {
  try {
    await rateLimiter.execute(async () => {
      await pingDiscord("Rate-limited ping!");
    });
  } catch (error) {
    console.error("Rate-limited ping failed:", error);
  }
}

async function main() {
  try {
    for (let i = 0; i < 10; i++) {
      await rateLimitedPing();
      await new Promise(resolve => setTimeout(resolve, 5000));
    }
    console.log('Pings completed.');
  } catch (error) {
    console.error('Error during ping loop:', error);
  }
}

main();
