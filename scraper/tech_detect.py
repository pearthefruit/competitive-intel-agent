"""Technology stack detection — identify frameworks, CDNs, analytics from page HTML and headers."""

import re

# Fingerprint patterns: (regex_pattern, technology_name)
# Checked against script srcs, inline JS, meta tags, link tags, and HTML content
FINGERPRINTS = {
    "Frontend Framework": [
        (r"react[\.-]dom|reactjs|react\.production", "React"),
        (r"/_next/|__NEXT_DATA__|next\.js", "Next.js"),
        (r"vue[\.-]|vuejs|__VUE__", "Vue.js"),
        (r"__NUXT__|/_nuxt/|nuxt\.js", "Nuxt.js"),
        (r"angular[\.-]|ng-version|angular\.io", "Angular"),
        (r"svelte|svelte-kit|__sveltekit", "Svelte"),
        (r"ember[\.-]|emberjs", "Ember.js"),
        (r"gatsby[\.-]|__gatsby", "Gatsby"),
        (r"remix[\.-]|__remixContext", "Remix"),
        (r"astro[\.-]|astro-island", "Astro"),
    ],
    "JavaScript Library": [
        (r"jquery[\.-]|jquery\.min", "jQuery"),
        (r"lodash[\.-]|lodash\.min", "Lodash"),
        (r"moment[\.-]|moment\.min", "Moment.js"),
        (r"gsap[\.-]|greensock", "GSAP"),
        (r"three[\.-]|three\.min", "Three.js"),
        (r"alpine[\.-]|x-data=", "Alpine.js"),
        (r"htmx[\.-]|hx-get|hx-post", "htmx"),
    ],
    "CSS Framework": [
        (r"tailwind|tw-", "Tailwind CSS"),
        (r"bootstrap[\.-]|bootstrap\.min", "Bootstrap"),
        (r"material[\.-]ui|mui[\.-]", "Material UI"),
        (r"bulma[\.-]|bulma\.min", "Bulma"),
        (r"chakra[\.-]ui", "Chakra UI"),
        (r"ant[\.-]design|antd", "Ant Design"),
    ],
    "Analytics": [
        (r"google-analytics|googletagmanager|gtag|ga\.js|analytics\.js|gtm\.js", "Google Analytics"),
        (r"segment[\.-]com|analytics\.min\.js.*segment|cdn\.segment", "Segment"),
        (r"mixpanel[\.-]com|mixpanel\.min", "Mixpanel"),
        (r"hotjar[\.-]com|hotjar\.js", "Hotjar"),
        (r"amplitude[\.-]com|amplitude\.min", "Amplitude"),
        (r"heap[\.-]io|heap-\d+", "Heap"),
        (r"fullstory[\.-]com|fullstory\.min", "FullStory"),
        (r"posthog[\.-]com|posthog\.js", "PostHog"),
        (r"plausible[\.-]io", "Plausible"),
        (r"clarity\.ms|clarity\.js", "Microsoft Clarity"),
    ],
    "Tag Manager": [
        (r"googletagmanager\.com/gtm|gtm\.js", "Google Tag Manager"),
        (r"tealium[\.-]com|tealium\.js", "Tealium"),
        (r"ensighten[\.-]com", "Ensighten"),
    ],
    "Marketing & CRM": [
        (r"hubspot[\.-]com|hs-scripts|hbspt", "HubSpot"),
        (r"marketo[\.-]com|munchkin", "Marketo"),
        (r"salesforce[\.-]com|pardot", "Salesforce/Pardot"),
        (r"drift[\.-]com|drift\.js", "Drift"),
        (r"intercom[\.-]com|intercom\.js|intercomSettings", "Intercom"),
        (r"zendesk[\.-]com|zdassets", "Zendesk"),
        (r"crisp[\.-]chat", "Crisp"),
        (r"qualified[\.-]com", "Qualified"),
        (r"6sense[\.-]com", "6sense"),
        (r"clearbit[\.-]com", "Clearbit"),
    ],
    "CDN & Hosting": [
        (r"cloudflare[\.-]com|cf-ray|cf-cache", "Cloudflare"),
        (r"cloudfront\.net", "AWS CloudFront"),
        (r"fastly[\.-]net|x-fastly", "Fastly"),
        (r"akamai[\.-]net|akamaized", "Akamai"),
        (r"vercel[\.-]app|vercel\.com|x-vercel", "Vercel"),
        (r"netlify[\.-]app|netlify\.com", "Netlify"),
        (r"herokuapp\.com", "Heroku"),
        (r"wpengine\.com", "WP Engine"),
    ],
    "CMS": [
        (r"wp-content|wp-includes|wordpress", "WordPress"),
        (r"contentful[\.-]com", "Contentful"),
        (r"prismic[\.-]io", "Prismic"),
        (r"sanity[\.-]io|sanity\.js", "Sanity"),
        (r"strapi[\.-]io", "Strapi"),
        (r"ghost[\.-]org|ghost-url", "Ghost"),
        (r"webflow[\.-]com", "Webflow"),
        (r"squarespace[\.-]com", "Squarespace"),
        (r"wix[\.-]com|wixstatic", "Wix"),
    ],
    "Payments": [
        (r"js\.stripe\.com|stripe[\.-]js", "Stripe"),
        (r"paypal[\.-]com|paypal\.js", "PayPal"),
        (r"braintree[\.-]com|braintree\.js", "Braintree"),
        (r"checkout\.shopify", "Shopify Payments"),
    ],
    "Performance & Monitoring": [
        (r"sentry[\.-]io|sentry\.js", "Sentry"),
        (r"datadog[\.-]com|dd-rum|datadoghq", "Datadog"),
        (r"newrelic[\.-]com|newrelic\.js|nr-data", "New Relic"),
        (r"bugsnag[\.-]com|bugsnag\.js", "Bugsnag"),
        (r"logrocket[\.-]com|logrocket\.js", "LogRocket"),
    ],
    "A/B Testing": [
        (r"optimizely[\.-]com|optimizely\.js", "Optimizely"),
        (r"launchdarkly[\.-]com", "LaunchDarkly"),
        (r"vwo[\.-]com|visualwebsiteoptimizer", "VWO"),
    ],
    "Authentication": [
        (r"auth0[\.-]com", "Auth0"),
        (r"okta[\.-]com", "Okta"),
        (r"clerk[\.-]com|clerk\.js", "Clerk"),
    ],
    "Search": [
        (r"algolia[\.-]com|algolia\.js|algoliasearch", "Algolia"),
        (r"elasticsearch|elastic[\.-]co", "Elasticsearch"),
    ],
}

# Header-based detection
HEADER_FINGERPRINTS = {
    "server": [
        (r"nginx", "Nginx"),
        (r"apache", "Apache"),
        (r"cloudflare", "Cloudflare"),
        (r"vercel", "Vercel"),
        (r"netlify", "Netlify"),
        (r"gws|google", "Google Web Server"),
    ],
    "x-powered-by": [
        (r"express", "Express.js (Node.js)"),
        (r"next\.js", "Next.js"),
        (r"php", "PHP"),
        (r"asp\.net", "ASP.NET"),
        (r"django", "Django"),
        (r"flask", "Flask"),
        (r"rails", "Ruby on Rails"),
    ],
}


def detect_technologies(pages):
    """Detect technologies across crawled pages.

    Args:
        pages: list of page dicts from site_crawler (must include 'html' or full text content)

    Returns:
        dict of {category: [(tech_name, confidence, found_on_pages), ...]}
    """
    # Track detections: {(category, tech): set(page_urls)}
    detections = {}

    for page in pages:
        url = page.get("url", "")

        # Build text corpus to search against
        # Combine multiple sources for comprehensive detection
        search_corpus = ""

        # HTML content (script tags, inline JS, meta tags)
        html = page.get("html", "")
        if html:
            search_corpus += html

        # If no raw HTML, reconstruct from extracted data
        if not html:
            # Script srcs from images/links won't capture scripts, but we can check headings, etc.
            for link in page.get("internal_links", []) + page.get("external_links", []):
                search_corpus += " " + link.get("url", "")

        # Check response headers
        headers = page.get("response_headers", {})
        for header_name, patterns in HEADER_FINGERPRINTS.items():
            header_value = headers.get(header_name, "")
            if not header_value:
                # Try case-insensitive lookup
                for k, v in headers.items():
                    if k.lower() == header_name:
                        header_value = v
                        break

            if header_value:
                for pattern, tech_name in patterns:
                    if re.search(pattern, header_value, re.IGNORECASE):
                        key = ("Infrastructure", tech_name)
                        if key not in detections:
                            detections[key] = set()
                        detections[key].add(url)

        # Check HTML/script patterns
        if search_corpus:
            for category, patterns in FINGERPRINTS.items():
                for pattern, tech_name in patterns:
                    if re.search(pattern, search_corpus, re.IGNORECASE):
                        key = (category, tech_name)
                        if key not in detections:
                            detections[key] = set()
                        detections[key].add(url)

    # Organize by category
    result = {}
    for (category, tech_name), pages_found in sorted(detections.items()):
        if category not in result:
            result[category] = []
        result[category].append({
            "name": tech_name,
            "pages_detected": len(pages_found),
        })

    return result


def format_tech_for_prompt(tech_dict, total_pages):
    """Format detected technologies into a string for the LLM prompt."""
    if not tech_dict:
        return "No technologies detected."

    lines = []
    for category, techs in tech_dict.items():
        lines.append(f"\n### {category}")
        for t in techs:
            coverage = f"{t['pages_detected']}/{total_pages} pages"
            lines.append(f"  - {t['name']} (found on {coverage})")

    return "\n".join(lines)
