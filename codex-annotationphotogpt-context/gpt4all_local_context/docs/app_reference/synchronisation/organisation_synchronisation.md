## Distinction essentielle côté laptop ↔ NAS

Tous les flux impliquant le laptop ne relèvent pas du même mécanisme.

### Flux 2 — déport unidirectionnel
Les gros fichiers (photos, audio, etc.) sont copiés du laptop vers le NAS via `robocopy`, en sens unique.

Objectif :
- décharger le laptop ;
- permettre la suppression locale sans impact sur le NAS ni le PC fixe.

### Flux 1, 3 et 4 — synchronisation bidirectionnelle cible
Les pièces documentaires, pièces produites par l’expert et données projet structurées ont vocation à être synchronisées en bidirectionnel entre laptop et NAS via `Syncthing`.

Objectif :
- maintenir une cohérence documentaire entre les environnements.

### Flux 5 — hors laptop
Les données projet techniques non destinées au laptop restent synchronisées entre NAS et PC fixe uniquement.

