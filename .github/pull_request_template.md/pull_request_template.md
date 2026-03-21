## 📝 Description
<!-- Briefly describe what this PR does and WHY -->


## 🔗 Related Issue
Closes #<!-- issue number -->

## 🛠 Type of Change
<!-- Check all that apply -->
- [ ] 🐛 Bug fix (non-breaking change that fixes an issue)
- [ ] ✨ New feature (non-breaking change that adds functionality)
- [ ] 💥 Breaking change (fix or feature that would cause existing functionality to change)
- [ ] 🧪 Tests (adding or updating tests)
- [ ] 📄 Docs / comments update
- [ ] 🔧 Refactor / tech debt
- [ ] 🚀 CI/CD / infra change
- [ ] 🔐 Security fix

## 🧪 How Has This Been Tested?
<!-- Describe the tests you ran. Provide instructions so reviewers can reproduce. -->
- [ ] Unit tests (`pytest agent/ -v`)
- [ ] Lint (`ruff check agent/ gui/`)
- [ ] Manual local test
- [ ] Docker build verified
- [ ] K8s manifest validated (`kubectl apply --dry-run=client`)

## 📸 Screenshots / Logs (if applicable)
<!-- Add screenshots or relevant log output -->

## ✅ Pre-Merge Checklist
<!-- All boxes must be checked before merging -->
- [ ] My code follows the project's code style
- [ ] I have performed a self-review of my code
- [ ] I have commented my code where necessary
- [ ] I have updated the documentation where relevant
- [ ] My changes generate no new warnings or errors
- [ ] I have added tests that prove my fix/feature works
- [ ] All new and existing tests pass
- [ ] No secrets or credentials are hard-coded
- [ ] Dependencies updated in `requirements.txt` if needed
- [ ] Docker images build successfully
- [ ] K8s manifests validated (if infra change)

## 🔍 Reviewer Notes
<!-- Any specific areas you'd like reviewers to focus on? -->

## 📊 Impact Analysis
<!-- Which components are affected? -->
- [ ] `agent/` - AI copilot core
- [ ] `agent/tools/` - Tool integrations (Jenkins/K8s/Nginx etc.)
- [ ] `gui/` - Streamlit frontend
- [ ] `deploy/` - Docker / K8s manifests
- [ ] `.github/` - CI/CD workflows
- [ ] `scripts/` - Data ingestion scripts
- [ ] `tests/` - Test suite
