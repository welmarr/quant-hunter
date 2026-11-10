# Hunter — Étapes et sous-étapes

Plan de finalisation de Quant Hunter (vision v2, novembre 2026). Mis à jour par Claude à chaque avancée.

Légende : `[x]` fait · `[~]` en cours · `[ ]` à faire · **(Toi)** = action qui dépend de Rymaa.

**Avancement : 17 / 42 sous-étapes terminées, 2 en cours.** Dernière mise à jour : 2026-11-09, 21 h 30.


## Phase 0 — Reprise et stabilisation (10/10)

- [x] **0.1** Audit du projet de Codex — Rapport du 3 nov.
- [x] **0.2** Sauvegarde du travail non commité — Branche snapshot/v0-wip-2026-11-03
- [x] **0.3** Vérification du dernier test complet de Codex — 3 704 tests réussis, 93,2 % de couverture
- [x] **0.4** Exécution des tests sur ton PC — Programme d'exécution sur ton PC, Python 3.14.7 et fichiers temporaires sur D:
- [x] **0.5** Relance de la suite complète sur le snapshot — 4 031 réussis, 1 test périmé corrigé ; 93,1 % de couverture
- [x] **0.6** Sauvegarde du lot non intégré de Codex sur une branche — Branche integrate/v0-product-extension
- [x] **0.7** Intégration du lot : signaux, métriques paper, archives, forwards FX, macro, planification — 42 fichiers intégrés, 400 tests ciblés réussis, mypy et ruff propres
- [x] **0.8** Suite complète, commit et envoi sur GitHub — Branches poussées sur GitHub le 9 nov.
- [x] **0.9** Rangement de .tools dans une archive sur D: — Archivé dans D:\QuantHunterArchive\tools-2026-10
- [x] **0.10** Preuve de sécurité Windows passée en option (décision inscrite) — Décision DEC-0050

## Phase 1 — Données et serveur (4/7)

- [ ] **1.1** Choix de l'hébergeur (≈ 40 $/mois) **(Toi)** — Proposition : Contabo Cloud VPS (24 Go, environ 17 $/mois) ; ton accord requis
- [~] **1.2** Déploiement de Hunter sur le serveur — Scripts prêts dans deploy/, en attente du serveur
- [x] **1.3** Connecteur prix actions/ETF — Yahoo quotidien : 45 ETF, depuis 1993 pour SPY
- [x] **1.4** Connecteur forex — Yahoo quotidien, 12 paires ; qualité moyenne, Dukascopy/OANDA prévus
- [x] **1.5** Connecteur macro à date — FRED, 34 séries ; vintages ALFRED dès qu'une clé FRED gratuite est fournie
- [x] **1.6** Connecteur crypto — Coinbase (5 cryptos) et taux de financement Kraken (3)
- [~] **1.7** Mise à jour quotidienne et contrôle qualité — Collecte et contrôles faits (99 séries, 0 échec) ; planification quotidienne sur le serveur

## Phase 2 — Stratégies et modèles (3/8)

- [x] **2.1** EXP-0001 : tendance sur ETF — Réussi sur les pertes, pas d'avantage de Sharpe
- [ ] **2.2** EXP-0001 inscrit au registre officiel du labo
- [x] **2.3** Filtres anti-hasard : Sharpe dégonflé, PBO — Sharpe dégonflé et PBO implémentés et testés
- [x] **2.4** EXP-0002 : carry et tendance FX — Réussite formelle mais sans avantage exploitable ; le carry seul est à retester
- [ ] **2.5** Momentum multi-actifs et ciblage de volatilité
- [ ] **2.6** Passerelle Qlib (Alpha158)
- [ ] **2.7** Modèles LightGBM et CatBoost
- [ ] **2.8** Les 15 familles de motifs deviennent des variables

## Phase 3 — Paper trading et suivi (0/5)

- [ ] **3.1** Comptes de démo Alpaca et OANDA **(Toi)** — Je ne peux pas créer de compte à ta place
- [ ] **3.2** Connecteurs courtier en paper
- [ ] **3.3** Exécution quotidienne des stratégies validées
- [ ] **3.4** Tableau de bord paper contre backtest
- [ ] **3.5** Alertes Telegram

## Phase 4 — Usine de recherche IA (0/7)

- [ ] **4.1** Agent d'hypothèses à partir des publications
- [ ] **4.2** Bac à sable de code et enregistrement automatique
- [ ] **4.3** Chronos-2 pour la volatilité et le risque
- [ ] **4.4** Signaux texte : Fed, SEC, actualités
- [ ] **4.5** Données vague 2 : EDGAR, COT, short interest
- [ ] **4.6** Données vague 3 : texte, marchés de prédiction
- [ ] **4.7** Détection de régimes

## Phase 5 — Portefeuille et argent réel (0/5)

- [ ] **5.1** Allocation : HRP, Black-Litterman, parité de risque
- [ ] **5.2** Limites de risque CVaR et arrêt d'urgence
- [ ] **5.3** Rétrogradation automatique des stratégies
- [ ] **5.4** 3 à 6 mois de paper cohérent avec le backtest
- [ ] **5.5** Décision de passer à l'argent réel **(Toi)**
