run:
	streamlit run app/main.py

export:
	python scripts/generate_word_report.py

check:
	@ls -lh data

clean:
	rm -f data/annotations.csv export/rapport.docx

help:
	@echo "Commandes disponibles :"
	@echo "  make run      - Lance l'application Streamlit"
	@echo "  make export   - Génère le rapport Word depuis annotations.csv"
	@echo "  make check    - Affiche le contenu du dossier data"
	@echo "  make clean    - Supprime annotations.csv et le rapport Word"