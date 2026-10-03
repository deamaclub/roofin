from . import Topic, Vertical

VERTICAL = Vertical(
    key="roofing",
    trade="roofing company",
    search_suffix="roofing companies",
    cta_phrases=("free estimate", "free inspection", "free quote", "free roof inspection", "get a quote",
                 "request a quote", "get an estimate", "schedule an inspection", "book an inspection"),
    default_cta="Get a Free Roof Inspection",
    osm_tags=(("craft", "roofer"),),
    osm_name_words=("roof",),
    hero_sample=(
        "## {city} Roof Repair & Replacement You Can Count On\n"
        "Leaks, storm damage, or a roof that's simply worn out — {name} inspects it for free and gives you "
        "a straight answer and a written price, usually within 48 hours.\n\n"
        "**[{cta}]**  ·  or call {phone}\n\n"
        "- Licensed & insured · Local {city} crew\n"
        "- Insurance claim help for storm and hail damage\n"
        "- Written warranty on every job"
    ),
    topics=(
        Topic(
            key="emergency",
            page_name="Emergency Roof Repair",
            review_words=("emergency", "same day", "same-day", "middle of the night", "came out right away",
                          "urgent", "tarp", "water coming in", "pouring in"),
            site_words=("emergency",),
            urgent=True,
            sample=(
                "## Emergency Roof Repair in {city}\n"
                "Water coming through the ceiling? Don't wait for it to get worse. {name} answers emergency "
                "calls fast, tarps and secures your roof the same day when possible, and then gives you a "
                "clear plan for the permanent repair.\n\n"
                "**Call now: {phone}** — or send a photo and your address below and we'll call you back.\n\n"
                "[ Name ] [ Phone ] [ Address ] [ What's happening? ]  **[Get Help Now]**"
            ),
        ),
        Topic(
            key="storm",
            page_name="Storm & Hail Damage",
            review_words=("storm", "hail", "wind damage", "high winds", "blew off", "tree fell", "tree came down",
                          "shingles off", "after the storm"),
            site_words=("storm", "hail", "wind damage"),
            urgent=True,
            sample=(
                "## Storm & Hail Damage Repair in {city}\n"
                "Missing shingles, dents from hail, or a tree limb on the roof? After a storm, the most "
                "important step is documenting the damage before your insurance adjuster arrives.\n\n"
                "{name} will:\n"
                "1. Inspect your roof for free and photograph every damaged area\n"
                "2. Help you understand what your policy should cover\n"
                "3. Meet your adjuster on-site if you want us there\n"
                "4. Repair or replace — with a written warranty\n\n"
                "**[Schedule a Free Storm Damage Inspection]**  ·  {phone}"
            ),
        ),
        Topic(
            key="insurance",
            page_name="Insurance Claims Help",
            review_words=("insurance", "claim", "adjuster", "deductible"),
            site_words=("insurance", "claim"),
            sample=(
                "## We Help With Your Roof Insurance Claim\n"
                "Insurance paperwork shouldn't stand between you and a dry home. {name} documents the damage, "
                "provides the photos and estimate your insurer needs, and can meet the adjuster at your "
                "property.\n\n"
                "**[{cta}]**  ·  {phone}"
            ),
        ),
        Topic(
            key="repair",
            page_name="Roof Repair",
            review_words=("leak", "leaking", "repair", "fixed", "patched", "flashing"),
            site_words=("repair", "leak"),
            sample=(
                "## Roof Leak Repair in {city}\n"
                "Not every leak means a new roof. {name} finds the actual source — flashing, a cracked boot, "
                "missing shingles — and fixes it right the first time.\n\n"
                "**[{cta}]**  ·  {phone}"
            ),
        ),
        Topic(
            key="replacement",
            page_name="Roof Replacement",
            review_words=("new roof", "replaced", "replacement", "re-roof", "reroof", "tear off", "tear-off",
                          "whole roof"),
            site_words=("replacement", "new-roof", "new roof", "re-roof", "reroof", "roof installation"),
            sample=(
                "## Roof Replacement in {city}\n"
                "When repairs stop making sense, {name} replaces your roof in as little as one day, protects "
                "your landscaping, and hauls away every nail. Financing available.\n\n"
                "**[{cta}]**  ·  {phone}"
            ),
        ),
        Topic(
            key="gutters",
            page_name="Gutters",
            review_words=("gutter", "gutters", "downspout"),
            site_words=("gutter",),
            sample=(
                "## Gutter Installation & Repair\n"
                "Overflowing or sagging gutters send water into your fascia and foundation. {name} installs "
                "seamless gutters and guards sized for {city} storms.\n\n"
                "**[{cta}]**  ·  {phone}"
            ),
        ),
    ),
)
