"""Debug script — shows exactly what the scraper finds and what prompt is sent to AI."""
from fetcher.scraper import scrape_today_posts
from extractor.prompt import COMBINED_PROMPT_TEMPLATE, build_restaurant_block, today_str
from utils.burmese import normalize_burmese
from config import load_restaurants

restaurants = load_restaurants()
all_blocks = []

for r in restaurants:
    print(f"\n{'='*60}")
    print(f"Restaurant: {r['name']}")
    print(f"{'='*60}")
    texts = scrape_today_posts(r["page_url"])
    for i, t in enumerate(texts):
        print(f"\n--- Block {i+1} ---")
        print(t)
    normalized = [normalize_burmese(t) for t in texts]
    all_blocks.append(build_restaurant_block(r["name"], normalized))

print(f"\n{'='*60}")
print("FULL PROMPT SENT TO AI:")
print(f"{'='*60}")
prompt = COMBINED_PROMPT_TEMPLATE.format(
    today=today_str(),
    restaurant_blocks="\n\n".join(all_blocks),
)
print(prompt)
