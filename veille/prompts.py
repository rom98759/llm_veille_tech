"""Prompts. Courts et très cadrés : pensés pour des petits modèles locaux (4-9B)."""

# Notation par grille de critères oui/non plutôt qu'une note libre 0-10 :
# les petits modèles saturent une note libre (8-10 partout), ils répondent mieux à des questions fermées.
# La note finale est calculée côté Python (process.JUDGE_WEIGHTS). Changer la grille => incrémenter la version.
JUDGE_VERSION = "grille-v1"

JUDGE_SYSTEM = """Tu es un analyste de veille technologique exigeant. La plupart des articles NE méritent PAS \
d'être retenus : sois strict, réponds "false" en cas de doute. Réponds UNIQUEMENT en JSON."""

JUDGE_USER = """Profil du lecteur :
{profile}

Axe de veille : {axis_title} — {axis_description}

Article :
- Titre : {title}
- Source : {source}
- Extrait : {summary}

Réponds à chaque question par true ou false :
- on_topic : l'article traite directement de l'axe « {axis_title} » (pas juste une mention) ;
- new_fact : il annonce un fait nouveau (sortie, faille, incident, résultat, décision), pas une opinion, \
un tutoriel générique, une rétrospective ou une promotion ;
- concrete : il contient des éléments techniques précis (versions, CVE, chiffres, noms de produits) ;
- actionable : le lecteur décrit dans le profil a quelque chose à faire ou à surveiller suite à cet article ;
- major : l'impact dépasse un cas isolé (largement utilisé, exploité activement, rupture technique) ;
- noise : c'est du marketing, un contenu sponsorisé, une levée de fonds, une rumeur ou un listicle.

Exemples :
- « CVE-2026-1234 : RCE exploitée activement dans OpenSSH 9.x, correctif publié » (axe cyber) → \
{{"on_topic": true, "new_fact": true, "concrete": true, "actionable": true, "major": true, "noise": false}}
- « 10 conseils pour sécuriser votre entreprise en 2026 » (axe cyber) → \
{{"on_topic": true, "new_fact": false, "concrete": false, "actionable": false, "major": false, "noise": true}}
- « La startup X lève 50 M$ pour son assistant IA » (axe ia) → \
{{"on_topic": true, "new_fact": true, "concrete": false, "actionable": false, "major": false, "noise": true}}

Format : {{"on_topic": bool, "new_fact": bool, "concrete": bool, "actionable": bool, "major": bool, \
"noise": bool, "reason": "<une phrase : pourquoi retenir ou écarter>"}}"""

SUMMARY_VERSION = "v2-resume-long"

SUMMARY_SYSTEM = """Tu rédiges des fiches de veille technologique en {language}, pour un lecteur qui veut \
être réellement informé sans ouvrir l'article. Sois précis et factuel : noms de produits, versions, CVE, \
chiffres, dates, acteurs. N'invente rien : uniquement ce qui est dans le texte. Réponds UNIQUEMENT en JSON."""

SUMMARY_USER = """Titre : {title}
Source : {source}

Texte :
{text}

Format :
{{"tldr": "<1 phrase d'accroche : le fait principal, avec le sujet nommé>",
  "summary": "<résumé complet de 5 à 8 phrases (120 à 200 mots) : contexte, ce qui est annoncé ou découvert, \
détails techniques, chiffres, qui est concerné, conséquences et suites attendues. Texte autonome et fluide.>",
  "key_points": ["<fait précis 1>", "<fait précis 2>", "<3 à 5 faits au total>"],
  "why_it_matters": "<1 à 2 phrases : impact concret pour le lecteur et ce qu'il devrait faire ou surveiller>",
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
