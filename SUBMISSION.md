# ApplyTrack Agent submission metadata

Complete the pending fields only after the private GitHub repository and Render service exist. Do not invent URLs, hashes, names, or invitation status.

- Full name: **PENDING - enter manually**
- Roll number: **PENDING - enter manually**
- Class / section: **PENDING - enter manually**
- University email: **PENDING - enter manually**
- GitHub username: **PENDING - enter manually**
- Agent name: `ApplyTrack Agent`
- Domain: `Job Application Tracker`
- Private GitHub repository URL: **PENDING - create repository manually**
- Final source commit hash: **PENDING - record after final commit**
- Working public agent interface URL: **PENDING - deploy on Render**
- GET `/health` URL: **PENDING - append `/health` to live service URL**
- POST `/arena/run` URL: **PENDING - append `/arena/run` to live service URL**
- GET `/arena/manifest` URL: **PENDING - append `/arena/manifest` to live service URL**
- API documentation URL: **PENDING - append `/docs` to live service URL**
- Hosting provider: `Render` (deployment pending)
- Default model and provider: `gemini-3.1-flash-lite` via Gemini, configured locally and in `render.yaml`
- Other models tested: `gemini-3.1-pro-preview` was attempted; balanced comparison remains pending quota availability
- Example input: `Track my Arbisoft AI Intern application.`
- Expected behavior: Search the sandbox, add the record when no duplicate exists, and return a completed structured response; no external submission occurs.
- Cold-start / restart limitations: Chat history and session application records are in memory and are lost on restart or redeploy. One worker is required.
- Instructor repository invitation status: **PENDING - invite manually**
- Public test result file: `evaluation/model_comparison_results_quota_limited.json` and `.csv` (first run archived; final balanced comparison pending)

## Deployment checklist

1. Push final code to a private GitHub repository.
2. Invite the instructor or required collaborator.
3. Create a Render Web Service from the repository.
4. Configure `GEMINI_API_KEY` and other environment variables in Render, never in source.
5. Deploy with one worker.
6. Verify the live interface and `/health`, `/arena/run`, `/arena/manifest`, and `/docs` endpoints.
7. Record the final commit hash.
8. Replace the pending metadata above.
9. Create the final ZIP and PDF submission files and submit them through the assignment portal.
