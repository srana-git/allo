# Validation technique — agent téléphonique bilingue pour le Québec sur ElevenLabs

**Pour :** un responsable TI d'une entreprise canadienne qui reçoit des appels du Québec ·
**Système :** allo (démo, concessionnaire fictif « Groupe Auto Laval ») · **Date :** octobre 2026 ·
**État :** suites de tests terminées; évaluation des voix non concluante; aucun appel réel

## Verdict

ElevenLabs peut exploiter dès aujourd'hui une ligne téléphonique en français d'abord pour le
Québec. Les appelants francophones ont reçu une réponse en français dans 99 à 100 % des tours de
l'agent. Les changements de langue en cours d'appel ont été suivis dans 98 % des tours après une
ronde de correctifs. **Le point faible, c'est l'appelant qui commence en anglais.** Dans une
conversation complète, l'agent reste parfois en français après une première phrase en anglais
(80 à 92 % des tours corrects pour le groupe anglophone). La solution est un routage déterministe
de la langue dès la première phrase, pas un autre ajustement du prompt.

## Ce qui a été testé

| Volet | Comment |
| --- | --- |
| Prise et déplacement de rendez-vous de service | Outils webhook reliés à un calendrier (Cloudflare Worker + D1) |
| Rappels de sécurité | API des rappels de Transports Canada, en direct, texte français ou anglais |
| FAQ (heures, navette, pneus, politiques) | Base de connaissances bilingue avec RAG |
| Comportement linguistique | Chaque tour de l'agent noté par un détecteur de langue déterministe, pas par un LLM |
| Robustesse | Joual, anglicismes, injection de prompt, fausse autorité, client fâché, propos confus (simulés en texte) |

Méthode : 40 scénarios de développement (16 en français, 12 en anglais, 8 changements de langue,
4 adversariaux) et des tests d'appels d'outils, chacun exécuté 3 fois avec l'API de simulation
d'ElevenLabs. Ensuite, 12 scénarios **réservés**, rédigés pendant le développement à partir de
situations absentes de la suite, tenus à l'écart de toutes les exécutions de développement, et
exécutés deux fois seulement après le gel de l'agent. Aucune modification de l'agent n'a été faite
à cause de leurs résultats.

## Résultats

| Mesure | Résultat |
| --- | --- |
| Scénarios réservés, agent gelé (`agent-frozen-v1`) | **16/24 exécutions (67 %)** · 18/24 (75 %) en excluant 2 erreurs de conception des tests |
| Fidélité linguistique, scénarios réservés | **139/140 tours de l'agent (99 %)** |
| Suite de développement, 1re exécution | 79/132 exécutions (60 %); 20 tests sur 44 réussis aux 3 exécutions |
| Les 24 scénarios avec un échec, réexécutés 3 fois après correctifs | 19/72 → 44/72 exécutions; les 20 autres, en non-régression : 19/20 |
| Fidélité linguistique, 1re exécution → après correctifs (les 44 scénarios) | Français 99 % → 100 % · changement en cours d'appel 87 % → 98 % · anglais 80 % → 92 % |

L'agent gelé contient deux modifications faites après ces réexécutions : un jeton de réservation
côté serveur et un accueil bilingue. Elles n'ont été vérifiées que sur des sous-ensembles. Le test
du jeton a réussi 18 exécutions sur 24 pour 8 scénarios. Le test de l'accueil a réussi 2 sur 4, et
2 sur 3 en non-régression : un scénario de changement de langue a échoué une fois, l'agent ayant
dit « One moment. » en anglais après que l'appelant fut passé au français.

Échecs des scénarios réservés, conservés tels quels : politique d'annulation non mentionnée au
complet (2 exécutions sur 2); un détail inventé sur le Wi-Fi; un appel sur des pneus usés où
l'agent a proposé des pneus neufs plutôt qu'une inspection ou un conseiller; une réponse en
anglais à un appelant francophone qui a dicté son numéro en chiffres anglais; une relecture
abrégée après qu'une plage horaire a été prise.

## Limites de ces données

- Les appelants simulés sont du texte. Ils testent la logique du dialogue, pas la reconnaissance
  vocale des accents, l'audio téléphonique ou le bruit ambiant. Aucun appel réel n'a été fait :
  la ligne téléphonique est configurée, mais pas testée.
- Petits échantillons : 2 ou 3 exécutions par scénario. Un score de 67 % a une marge d'erreur
  large.
- Une seule entreprise fictive, une seule base de connaissances. Votre FAQ et vos systèmes
  feront bouger les chiffres.
- La qualité des voix a été notée à l'aveugle par une seule personne de langue maternelle
  québécoise. Le résultat n'est pas concluant : la même lettre a été choisie aux six lignes. Une
  vraie réponse demande plusieurs auditeurs.
- Réalisé sur le forfait Creator. Les appels simultanés et la latence sous charge n'ont pas été
  testés.
- Le SIP passait par TCP, avec chiffrement des médias permis mais non exigé. TLS et SRTP exigé
  sont offerts sur tous les forfaits et vont de soi en production.

## Recommandations

1. **Router la langue avant le LLM.** Détecter la langue de la première phrase de l'appelant avec
   la reconnaissance vocale et fixer la langue de la session dès le premier tour. Garder l'outil
   `language_detection`, piloté par le LLM, pour les changements suivants : il a obtenu 98 %.
   La pratique de la Charte de la langue française (modifiée par la loi 96) reste la règle :
   accueillir d'abord en français.
2. **Placer chaque écriture derrière un jeton côté serveur.** Le serveur refuse une réservation ou
   un déplacement sans un jeton émis par `prepare_booking`, qui fige les détails et renvoie la
   phrase exacte à relire. Une écriture sans relecture générée par le serveur est donc
   impossible. Que l'appelant ait bien entendu et accepté cette relecture dépend encore du
   modèle; les tests le mesurent, et le scénario réservé H01 compte un échec. Avant le jeton, le
   scénario « l'appelant change un détail pendant la relecture » réussissait 1 fois sur 3 dans
   deux exécutions; après, 3 fois sur 3.
3. **Générer les listes de faits des tests à partir de la base de connaissances.** Les listes
   copiées à la main ont dérivé trois fois dans ce projet et ont causé de faux échecs.
4. **Conditionner chaque mise en production à une suite réservée.** Geler l'agent, puis exécuter
   des scénarios sur lesquels il n'a jamais été ajusté.

## Ce qu'ajoute un déploiement Enterprise

- **Appels simultanés et SLA** dimensionnés selon le volume; ce test a traité un appel à la fois.
- **Gestion des données :** mode sans conservation, et résidence des données dans l'Union
  européenne, en Inde ou à Singapour. Aucune de ces régions n'est au Canada : la Loi 25 exige
  donc, dans toutes les configurations, une évaluation des facteurs relatifs à la vie privée
  avant qu'un renseignement personnel ne sorte du Québec.
- **Réseau :** une plage d'IP statiques pour les listes d'autorisation SIP sortantes. Ce test a
  plutôt limité l'entrée aux IP de signalisation du fournisseur téléphonique.
- **Intégration :** le même modèle d'outils webhook se branche sur un vrai DMS ou CRM; seul le
  Worker change.

Dépôt, fichiers de résultats et scripts pour reproduire chaque chiffre : `README.md`,
`evals/results/`.
