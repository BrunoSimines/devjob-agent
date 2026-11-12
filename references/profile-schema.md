# Structured resume extraction (JSON)

Produce this JSON from the text returned by `devjob profile import <file> --text-only`.
Omit fields you can't find. Never fill gaps with guesses.

`source` values:
- `resume`: the value is literally present in the resume text (the CLI verifies and downgrades if not found).
- `inferred`: you deduced it (e.g. a soft skill from a described behaviour). Add `evidence` with the exact excerpt.
- `user`: only if the user stated it in this conversation.

```json
{
  "contact": {
    "name": {"value": "Joana Exemplo", "source": "resume"},
    "email": {"value": "joana@example.com", "source": "resume"},
    "phone": {"value": "+55 11 91234-5678", "source": "resume"},
    "location": {"value": "São Paulo, SP", "source": "resume"},
    "linkedin": {"value": "linkedin.com/in/joana", "source": "resume"},
    "github": {"value": "github.com/joana", "source": "resume"}
  },
  "summary": {"value": "Engenheira de software backend ...", "source": "resume"},
  "experiences": [
    {
      "title": "Engenheira de Software Sênior",
      "company": "Acme Pagamentos",
      "start": "2021-01",
      "end": "present",
      "location": "Remoto",
      "technologies": ["Java", "Spring Boot", "Kafka"],
      "highlights": [
        {"value": "Reduzi a latência de APIs REST em 35% com cache Redis.", "source": "resume"}
      ]
    }
  ],
  "projects": [{"value": "Biblioteca open source X: ...", "source": "resume"}],
  "hard_skills": [{"value": "Java", "source": "resume"}],
  "soft_skills": [
    {"value": "Liderança", "source": "inferred", "evidence": "Liderei a migração de um monólito"}
  ],
  "education": [{"value": "Bacharelado em Ciência da Computação - Universidade Exemplo (2012 - 2016)", "source": "resume"}],
  "certifications": [{"value": "AWS Certified Developer - Associate (2024)", "source": "resume"}],
  "languages": [{"language": "Inglês", "level": "C1", "source": "resume"}],
  "specializations": [{"value": "IAM", "source": "inferred", "evidence": "serviços de autenticação com OAuth 2.0 e Keycloak"}]
}
```

Rules:
- Dates: `YYYY-MM` when the month is known, `YYYY` otherwise, `present` for current roles. Unknown dates: omit.
- Highlights: copy the sentence from the resume (you may fix line breaks). Do not merge, embellish or add metrics.
- `technologies`: only technologies named in that experience's text.
- Languages: CEFR level (`A1`..`C2`) or `native`. Map words conservatively (fluente/advanced → `C1`, intermediário → `B1`). If the resume gives no level, omit `level`.
- Soft skills are `resume` only when listed explicitly (e.g. in a skills section). Otherwise `inferred` with evidence.
