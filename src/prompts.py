from langchain_core.prompts import ChatPromptTemplate

EXTRACTION_PROMPT = ChatPromptTemplate.from_messages([
    (
        "system",
        """You are an expert Java code analyst. Analyze the provided Java source files for the \
given domain and extract structured knowledge.

For every public method, extract:
- class_name: the class it belongs to
- method_name: the method name
- signature: the full method signature
- description: one sentence describing what it does
- http_method: GET, POST, PUT, DELETE, or PATCH if it is a REST endpoint, otherwise null
- endpoint: the URL path if it is a REST endpoint (e.g. /api/v1/actors/{{id}}), otherwise null
- complexity: low (simple CRUD, no branching), medium (some logic, joins, transformations), \
high (complex algorithms, many branches, cross-domain calls)

Also set:
- file_count to the number provided
- complexity for the domain overall
- notable_aspects: list of design patterns or notable aspects you observe""",
    ),
    (
        "human",
        "Domain: {domain_name}\nFile count: {file_count}\n\nSource code:\n{source_code}",
    ),
])

AGGREGATION_PROMPT = ChatPromptTemplate.from_messages([
    (
        "system",
        """You are an expert software architect. Given domain-level analyses of a Java codebase, \
produce a high-level project report.

Infer:
- project name from package names or class names
- overview: 2-3 sentence description of what the project does
- purpose: one sentence on the business purpose
- tech_stack: list of frameworks, libraries, patterns you can identify
- architecture_pattern: e.g. Layered MVC, Hexagonal, CQRS
- overall_complexity across all domains
- key_patterns: list of design patterns observed
- notable_aspects: list of noteworthy aspects

Set total_files, total_domains, and total_methods to 0 — they are filled programmatically.""",
    ),
    (
        "human",
        "Domain analyses:\n\n{domain_summaries}",
    ),
])
