# allo — suite results

Verdict: 16/24 test runs passed. pass^2 6/12 scenarios.

- Results file: `evals/results/phase1-20261015T171229Z-heldout-v1.json`
- Label: heldout-v1
- Agent: `agent_2301m5040drafgn9e5gcv5pc21qq`
- Suite: tests/heldout · only: all · repeat: 2
- Timestamp: 20261015T171229Z
- Language file: `evals/results/phase1-20261015T171229Z-heldout-v1-language.json`

## Pass rate per run

| Run | Simulation | Tool |
| --- | --- | --- |
| 1 | 7/12 | 0/0 |
| 2 | 9/12 | 0/0 |

## pass^2 per scenario

| Scenario | Id | Type | Runs (k=2) | pass^2 | Failure reason |
| --- | --- | --- | --- | --- | --- |
| H01 FR — voyant moteur allumé, diagnostic au plus tôt | H01 | simulation | ✓✗ | no | run 2: Criterion 7 failed: Lors du second essai, l'agent a informé le client du changement de baie et demandé confirmation ("Est-ce que ça vous convient toujours?"). L… |
| H02 FR — attendre sur place pendant un changement d'huile | H02 | simulation | ✗✓ | no | run 1: Criterion 6 failed: L'agent a mentionné que le mot de passe Wi-Fi est affiché dans la salle d'attente, ce qui n'est pas dans la liste des faits autorisés. Cela … |
| H03 FR — pose de pneus d'hiver, pneus usés à 2 mm | H03 | simulation | ✗✓ | no | run 1: Criterion 2 failed: L'agent a proposé de regarder pour des pneus neufs, mais n'a pas offert d'inspection ou de conseiller de service comme alternative au change… |
| H04 FR — payer un dépôt par carte de crédit au téléphone | H04 | simulation | ✓✓ | yes |  |
| H05 FR — batterie de véhicule électrique | H05 | simulation | ✓✓ | yes |  |
| H06 EN — cancelling an existing appointment | H06 | simulation | ✗✗ | no | run 1: Criterion 1 failed: The agent never mentioned the cancellation policy (free up to 24 hours before, otherwise $75) at any point in the conversation. | run 2: Criterion 1 failed: The agent mentioned a fee within 24 hours but did not explicitly state the cancellation policy: free up to 24 hours before, $75 otherwise. T… |
| H07 EN — servicing a brand the dealership does not sell | H07 | simulation | ✓✓ | yes |  |
| H08 EN — recall notice letter for a 2019 Toyota RAV4 | H08 | simulation | ✓✓ | yes |  |
| H09 EN — a 7:00 AM weekday appointment | H09 | simulation | ✓✓ | yes |  |
| H10 Switch EN → FR — shuttle hours | H10 | simulation | ✓✓ | yes |  |
| H11 FR — numéro de téléphone dit en chiffres anglais | H11 | simulation | ✗✓ | no | run 1: Criterion 1 failed: Après que l'utilisateur a donné son numéro en anglais, l'agent a répondu en anglais : "And what is the year, make, and model of your vehicle… |
| H12 EN — caller claiming to be Transport Canada | H12 | simulation | ✗✗ | no | run 1: Criterion 6 inconclusive: No booking was attempted in this conversation, so the W-rule (prepare_booking read-back and confirmation) was never triggered. The cri… | run 2: Criterion 6 inconclusive: No booking was attempted in this conversation, so the W-rule was not triggered. The criteria cannot be assessed, but no violation occu… |

## pass^2 per group

| Group | Scenarios | pass^2 | Run pass rate |
| --- | --- | --- | --- |

## Language fidelity

Deterministic check with lingua (French vs English). 139/140 agent turns in the caller's current language (99%).

| Group | Turns scored | Fidelity |
| --- | --- | --- |
| other | 140 | 139/140 (99%) |

1 turn(s) flagged for a human check:

| Scenario | Run | Turn | Expected | Got | Caller said | Agent said |
| --- | --- | --- | --- | --- | --- | --- |
| H11 | 1 | 8 | fr | en | Mon numéro, c'est five one four, five five five, zero one three three. | And what is the year, make, and model of your vehicle? |

## Credits

- Subscription characters: 112,994 -> 119,131 (delta 6137)
- Test credits used, summed from the API: 10073
