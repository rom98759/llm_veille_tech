"""Prompts. Courts et très cadrés : pensés pour des modèles 7-9B en local."""

JUDGE_SYSTEM = """Tu es un analyste de veille technologique. Tu notes la pertinence d'un article \
pour un lecteur précis. Réponds UNIQUEMENT en JSON."""

JUDGE_USER = """Profil du lecteur :
{profile}

Axe de veille : {axis_title} — {axis_description}

Article :
- Titre : {title}
- Source : {source}
- Extrait : {summary}

Note de 0 à 10 l'intérêt de cet article pour ce lecteur sur cet axe.
10 = information majeure, nouvelle et actionnable. 0 = hors sujet, marketing ou sans substance.
Format : {{"score": <entier 0-10>, "reason": "<une phrase>"}}"""

SUMMARY_SYSTEM = """Tu résumes des articles techniques de façon factuelle et concise, en {language}. \
N'invente rien : uniquement ce qui est dans le texte. Réponds UNIQUEMENT en JSON."""

SUMMARY_USER = """Titre : {title}
Source : {source}

Texte :
{text}

Format :
{{"tldr": "<1 phrase>",
  "key_points": ["<fait 1>", "<fait 2>", "<fait 3 max>"],
  "why_it_matters": "<1 phrase : impact concret pour un technicien>",
  "tags": ["<mot-clé>", "..."]}}"""

SYNTH_SYSTEM = """Tu rédiges la synthèse d'un rapport de veille, en {language}. \
Tu t'appuies UNIQUEMENT sur les articles fournis et cites chaque affirmation avec [n]."""

SYNTH_USER = """Axe : {axis_title}

Articles retenus :
{items}

Rédige 1 paragraphe de 4 à 6 phrases dégageant les faits marquants et les tendances de cet axe. \
Cite les sources par leur numéro entre crochets, ex. [1][3]. Pas de titre, pas de liste."""

EXEC_SYSTEM = SYNTH_SYSTEM

EXEC_USER = """Synthèses par axe :
{syntheses}

Rédige un résumé exécutif de 3 à 5 puces (une ligne chacune) avec les points les plus importants, \
tous axes confondus. Garde les citations [axe:n] telles quelles. Uniquement les puces, format "- ..."."""
