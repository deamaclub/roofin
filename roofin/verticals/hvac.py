from . import Topic, Vertical

VERTICAL = Vertical(
    key="hvac",
    trade="heating & cooling company",
    search_suffix="HVAC companies",
    cta_phrases=("schedule service", "book service", "free estimate", "free quote", "request service",
                 "get a quote", "book online", "schedule online"),
    default_cta="Schedule Service",
    osm_tags=(("craft", "hvac"),),
    osm_name_words=("hvac", "heating", "air conditioning", "furnace"),
    hero_sample=(
        "## Heating & Cooling Service in {city}\n"
        "No heat, no AC, or a system that just isn't keeping up — {name} diagnoses it fast and gives you an "
        "upfront price before any work starts.\n\n"
        "**[{cta}]**  ·  or call {phone}"
    ),
    topics=(
        Topic(
            key="emergency",
            page_name="24/7 Emergency HVAC Service",
            review_words=("emergency", "no heat", "no ac", "no air", "middle of the night", "same day",
                          "weekend", "came out right away"),
            site_words=("emergency", "24/7", "24-7"),
            urgent=True,
            sample=(
                "## No Heat? No AC? We Answer 24/7\n"
                "{name} has technicians on call in {city} nights and weekends.\n\n"
                "**Call now: {phone}** — or request a callback below.\n\n"
                "[ Name ] [ Phone ] [ What's happening? ]  **[Get Help Now]**"
            ),
        ),
        Topic(
            key="maintenance",
            page_name="Maintenance Plans",
            review_words=("maintenance", "tune-up", "tune up", "annual service", "service plan"),
            site_words=("maintenance", "tune-up", "tune up", "service plan", "membership"),
            sample=(
                "## Maintenance Plans\n"
                "Two tune-ups a year, priority scheduling, and no overtime fees. Join {name}'s plan and "
                "catch problems before they leave you without heat or AC.\n\n"
                "**[{cta}]**  ·  {phone}"
            ),
        ),
        Topic(
            key="install",
            page_name="System Replacement",
            review_words=("new furnace", "new ac", "new system", "installed", "replacement", "heat pump"),
            site_words=("installation", "replacement", "new system", "heat pump"),
            sample=(
                "## Furnace, AC & Heat Pump Replacement\n"
                "Get a written, no-pressure quote from {name}, with financing and rebate help included.\n\n"
                "**[{cta}]**  ·  {phone}"
            ),
        ),
    ),
)
