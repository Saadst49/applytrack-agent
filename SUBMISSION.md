# ApplyTrack Agent submission metadata

- Full name: Muhammad Saad
- Roll number: 23I-0667
- Class / section: AI-A
- University email: i230667@isb.nu.edu.pk
- GitHub username: Saadst49
- Agent name: `ApplyTrack Agent`
- Domain: `Job Application Tracker`
- Private GitHub repository URL: [https://github.com/Saadst49/applytrack-agent](https://github.com/Saadst49/applytrack-agent)
- Final source commit hash: **PENDING - record after final metadata commit** (pre-metadata reference: `922426e9b56f2c906aa9e2b258c3db964d3f1c7d`)
- Working public agent interface URL: [https://applytrack-agent.onrender.com/](https://applytrack-agent.onrender.com/)
- GET `/health` URL: [https://applytrack-agent.onrender.com/health](https://applytrack-agent.onrender.com/health)
- GET `/models` URL: [https://applytrack-agent.onrender.com/models](https://applytrack-agent.onrender.com/models)
- POST `/arena/run` URL: [https://applytrack-agent.onrender.com/arena/run](https://applytrack-agent.onrender.com/arena/run)
- GET `/arena/manifest` URL: [https://applytrack-agent.onrender.com/arena/manifest](https://applytrack-agent.onrender.com/arena/manifest)
- API documentation URL: [https://applytrack-agent.onrender.com/docs](https://applytrack-agent.onrender.com/docs)
- Hosting provider: `Render`
- Default model and provider: `gemini-3.1-flash-lite` via Gemini, configured locally and in `render.yaml`
- Other models tested: `gemini-3.1-pro-preview` was attempted; balanced comparison remains pending quota availability
- Example input: `Track my Arbisoft AI Intern application.`
- Expected behavior: Search the sandbox, add the record when no duplicate exists, and return a completed structured response; no external submission occurs.
- Cold-start / restart limitations: Chat history and session application records are in memory and are lost on restart or redeploy. One worker is required.
- Instructor repository invitation status: **PENDING - confirm manually**
- Public test result file: [`evaluation/public_cases.json`](evaluation/public_cases.json), [`evaluation/run_public_tests.py`](evaluation/run_public_tests.py); unit tests: `29/29`, deterministic public Arena tests: `13/13`

## Deployment checklist

1. Push final code to the private GitHub repository.
2. Invite the instructor or required collaborator.
3. Configure `GEMINI_API_KEY` and other environment variables in Render, never in source.
4. Deploy with one worker.
5. Verify the live interface and `/health`, `/models`, `/arena/run`, `/arena/manifest`, and `/docs` endpoints.
6. Record the final commit hash externally; the commit-hash field above cannot contain its own hash.
7. Create the final ZIP and PDF submission files and submit them through the assignment portal.
