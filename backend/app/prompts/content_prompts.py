"""Prompt templates for the Content Creation Agent.

Two kinds of thing live here:

* `*_PROMPT` constants — the **system** message for each task. These carry
  the stable parts: role, task, constraints, output requirements. They never
  contain user data.
* `build_*` functions — the **user** message. These carry the variable
  parts: the topic, the source text, the requested tone.

Splitting them that way is the point of the system/user distinction. The
system message tells the model who it is and what rules it must follow; the
user message is the specific job. Concatenating both into one blob makes it
easy for user text to argue with the instructions.

Grounding rules matter here. Every task except generation transforms text the
user supplied, so each of those prompts forbids inventing facts. Generation
is the one place where creating new content is the actual request.
"""

from app.schemas.content_schemas import (
    Audience,
    ContentFormat,
    ContentLength,
    ContentType,
    SummaryType,
    Tone,
)

# --- Descriptive vocabularies ----------------------------------------------
#
# "professional" alone is vague. Spelling out what each option means gives the
# model something concrete to aim at and makes results far more consistent.

TONE_GUIDANCE: dict[Tone, str] = {
    Tone.PROFESSIONAL: "polished and business-appropriate, confident but not stiff",
    Tone.FORMAL: "formal and impersonal; no contractions, no colloquialisms",
    Tone.FRIENDLY: "warm and approachable, like explaining to a colleague you like",
    Tone.CASUAL: "relaxed and conversational; contractions and everyday words are fine",
    Tone.PERSUASIVE: "compelling and benefit-led, building toward a clear call to action",
    Tone.SIMPLE: "plain and direct; short sentences, common words, no jargon",
    Tone.ACADEMIC: "precise and scholarly, measured claims, formal register",
}

AUDIENCE_GUIDANCE: dict[Audience, str] = {
    Audience.BEGINNER: (
        "someone new to the subject; define every term on first use and rely on "
        "everyday analogies"
    ),
    Audience.STUDENT: (
        "a college student; assume general education but not subject expertise, "
        "and favour worked examples"
    ),
    Audience.DEVELOPER: (
        "a working software developer; technical vocabulary is fine, code-level "
        "detail and trade-offs are welcome"
    ),
    Audience.TECHNICAL_PROFESSIONAL: (
        "an experienced technical professional; be precise and concise, skip "
        "the basics, do not over-explain"
    ),
    Audience.GENERAL_AUDIENCE: (
        "a general adult reader; avoid jargon, and briefly explain any term you "
        "cannot avoid"
    ),
    Audience.EXECUTIVE: (
        "a senior decision-maker; lead with impact, cost and risk, keep detail "
        "minimal and outcomes prominent"
    ),
}

LENGTH_GUIDANCE: dict[ContentLength, str] = {
    ContentLength.SHORT: "roughly 150-250 words",
    ContentLength.MEDIUM: "roughly 400-600 words",
    ContentLength.LONG: "roughly 800-1200 words",
}

CONTENT_TYPE_GUIDANCE: dict[ContentType, str] = {
    ContentType.BLOG: "a blog post with a clear title, short paragraphs and subheadings",
    ContentType.ARTICLE: "a structured article with an introduction, body and conclusion",
    ContentType.EMAIL: "an email with a subject line, greeting, body and sign-off",
    ContentType.SOCIAL_MEDIA: (
        "a short social media post; punchy opening, minimal length, a few relevant "
        "hashtags at the end"
    ),
    ContentType.TECHNICAL_EXPLANATION: (
        "a technical explanation that builds from concept to detail, with examples"
    ),
    ContentType.PRODUCT_DESCRIPTION: (
        "a product description that leads with benefits and ends with a call to action"
    ),
}

SUMMARY_TYPE_GUIDANCE: dict[SummaryType, str] = {
    SummaryType.SHORT: (
        "a single tight paragraph of exactly 2-4 sentences capturing only the "
        "main point. Do not use bullets or headings"
    ),
    SummaryType.DETAILED: (
        "a fuller summary with 2-4 short paragraphs when the source has enough "
        "material. Cover the main argument and supporting points. For very short "
        "source text, write at least 4 complete sentences instead of collapsing "
        "the answer into fragments"
    ),
    SummaryType.BULLET_POINTS: (
        "5-8 markdown bullet points, one idea per bullet, each a complete sentence"
    ),
}

FORMAT_GUIDANCE: dict[ContentFormat, str] = {
    ContentFormat.PARAGRAPH: "flowing prose paragraphs with no bullets or headings",
    ContentFormat.BULLET_POINTS: "a bulleted list, one idea per bullet",
    ContentFormat.ARTICLE: "an article with a title, subheadings and a conclusion",
    ContentFormat.EMAIL: "an email with a subject line, greeting, body and sign-off",
    ContentFormat.REPORT: (
        "a structured report with clear section headings and a short summary first"
    ),
    ContentFormat.SOCIAL_MEDIA: "a short social media post with a strong opening line",
}

# Repeated across every transformation task, so it is written once.
_NO_INVENTION_RULE = (
    "Use only information present in the source text. Do not add facts, "
    "figures, names or claims that do not appear there. If the source is "
    "unclear or incomplete, reflect that rather than filling the gap."
)

_OUTPUT_ONLY_RULE = (
    "Return only the requested content. Do not add preambles such as "
    '"Here is your content", do not explain what you did, and do not wrap '
    "the whole response in code fences."
)


# --- System prompts ---------------------------------------------------------

CONTENT_GENERATION_PROMPT = f"""You are a professional content writer.

TASK
Write original content that matches the requested type, tone, audience and \
length exactly.

CONSTRAINTS
- Follow the requested content type's conventions.
- Match the requested tone throughout.
- Pitch every explanation at the requested audience.
- Stay within the requested length.
- Be specific. Prefer concrete examples over generic statements.
- Do not fabricate statistics, quotes, studies or sources. Write in general \
terms instead of inventing a number.

OUTPUT
{_OUTPUT_ONLY_RULE}"""


SUMMARIZATION_PROMPT = f"""You are an expert summarizer.

TASK
Condense the source text into the requested style of summary.

CONSTRAINTS
- {_NO_INVENTION_RULE}
- Preserve the source's meaning and emphasis; do not editorialise or add \
your own opinion.
- Keep the original's terminology where it matters.

OUTPUT
{_OUTPUT_ONLY_RULE}"""


REWRITE_PROMPT = f"""You are an expert editor.

TASK
Rewrite the source text according to the user's instructions.

CONSTRAINTS
- Preserve the original meaning unless the instructions explicitly ask you \
to change it.
- {_NO_INVENTION_RULE}
- Improve clarity, flow and word choice; remove redundancy.
- Keep roughly the same length unless told otherwise.

OUTPUT
{_OUTPUT_ONLY_RULE}"""


TONE_TRANSFORMATION_PROMPT = f"""You are an expert editor specialising in tone.

TASK
Rewrite the source text in the requested tone.

CONSTRAINTS
- Change style only. The factual meaning must stay identical.
- Do not add, remove or soften any fact, figure or claim.
- {_NO_INVENTION_RULE}
- Keep roughly the same length and structure.

OUTPUT
{_OUTPUT_ONLY_RULE}"""


AUDIENCE_ADAPTATION_PROMPT = f"""You are an expert at adapting writing for \
different readers.

TASK
Rewrite the source text so it lands well with the requested audience.

CONSTRAINTS
- Adjust vocabulary, explanation depth, terminology and examples.
- The underlying facts must not change. Simplifying is allowed; altering \
meaning is not.
- {_NO_INVENTION_RULE}
- Where you simplify a technical term, keep the correct term in parentheses \
on first use.

OUTPUT
{_OUTPUT_ONLY_RULE}"""


FORMAT_TRANSFORMATION_PROMPT = f"""You are an expert at restructuring content.

TASK
Reformat the source text into the requested format.

CONSTRAINTS
- Change structure and presentation only, not the facts.
- Keep all substantive information from the source.
- {_NO_INVENTION_RULE}
- Follow the target format's conventions precisely.

OUTPUT
{_OUTPUT_ONLY_RULE}"""


INFORMATION_EXTRACTION_PROMPT = """You are a precise information extraction \
system.

TASK
Extract structured information from the source text and return it as JSON.

CONSTRAINTS
- Extract only what appears in the source. Never infer, guess or invent an \
entity, fact or figure.
- If a category has nothing in the source, return an empty array for it.
- Keep each item short and self-contained.

OUTPUT
Return a single valid JSON object and nothing else. No markdown, no code \
fences, no commentary. Use exactly this shape:

{
  "entities": ["people, organisations, products, places named in the text"],
  "key_points": ["the main ideas, one per item"],
  "facts": ["specific verifiable statements, including any figures or dates"],
  "keywords": ["important topic words and phrases"]
}"""


# --- User message builders --------------------------------------------------


def build_generation_prompt(
    topic: str,
    content_type: ContentType,
    tone: Tone,
    audience: Audience,
    length: ContentLength,
    additional_instructions: str | None = None,
) -> str:
    """User message for content generation."""
    parts = [
        f"Topic: {topic}",
        f"Content type: {CONTENT_TYPE_GUIDANCE[content_type]}",
        f"Tone: {TONE_GUIDANCE[tone]}",
        f"Audience: {AUDIENCE_GUIDANCE[audience]}",
        f"Length: {LENGTH_GUIDANCE[length]}",
    ]
    if additional_instructions:
        parts.append(f"Additional instructions: {additional_instructions}")
    parts.append("\nWrite the content now.")
    return "\n".join(parts)


def build_summarization_prompt(text: str, summary_type: SummaryType) -> str:
    """User message for summarization."""
    return (
        f"Summary type: {summary_type.value}\n"
        f"Summary style: {SUMMARY_TYPE_GUIDANCE[summary_type]}\n\n"
        f"Source text:\n\"\"\"\n{text}\n\"\"\"\n\n"
        "Write the summary now. Follow the requested summary type exactly."
    )


def build_rewrite_prompt(text: str, instructions: str) -> str:
    """User message for rewriting."""
    return (
        f"Instructions: {instructions}\n\n"
        f"Source text:\n\"\"\"\n{text}\n\"\"\"\n\n"
        "Write the rewritten text now."
    )


def build_tone_prompt(text: str, tone: Tone) -> str:
    """User message for tone transformation."""
    return (
        f"Target tone: {tone.value} - {TONE_GUIDANCE[tone]}\n\n"
        f"Source text:\n\"\"\"\n{text}\n\"\"\"\n\n"
        "Rewrite it in the target tone now."
    )


def build_audience_prompt(text: str, audience: Audience) -> str:
    """User message for audience adaptation."""
    return (
        f"Target audience: {audience.value} - {AUDIENCE_GUIDANCE[audience]}\n\n"
        f"Source text:\n\"\"\"\n{text}\n\"\"\"\n\n"
        "Rewrite it for that audience now."
    )


def build_format_prompt(text: str, content_format: ContentFormat) -> str:
    """User message for format transformation."""
    return (
        f"Target format: {content_format.value} - {FORMAT_GUIDANCE[content_format]}\n\n"
        f"Source text:\n\"\"\"\n{text}\n\"\"\"\n\n"
        "Reformat it now."
    )


def build_extraction_prompt(text: str) -> str:
    """User message for information extraction."""
    return (
        f"Source text:\n\"\"\"\n{text}\n\"\"\"\n\n"
        "Extract the information and return the JSON object now."
    )
