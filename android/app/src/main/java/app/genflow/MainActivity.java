package app.genflow;

import android.app.*;
import android.os.*;
import android.content.*;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.text.InputType;
import android.view.*;
import android.widget.*;
import org.json.*;
import java.io.*;
import java.util.concurrent.*;

public class MainActivity extends Activity {
    private Api api;
    private LinearLayout root, content, navigation;
    private final ExecutorService executor = Executors.newSingleThreadExecutor();
    private final Handler handler = new Handler(Looper.getMainLooper());
    private int screen = 0;
    private String selectedJob = null, uploadPath = null, exportPath = null;
    private volatile boolean alive = true, busy = false, polling = false;
    private EditText command, script;
    private String commandDraft = "", scriptDraft = "";
    private static final int INK = 0xFF17171C, MUTED = 0xFF74747E, BG = 0xFFF5F5F7, ACCENT = 0xFF6057DB;
    interface Task { void run() throws Exception; }

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        api = new Api(this);
        if (state != null) {
            selectedJob = state.getString("job");
            uploadPath = state.getString("upload");
            exportPath = state.getString("export");
            commandDraft = state.getString("command", "");
            scriptDraft = state.getString("script", "");
        }
        if (api.signedIn()) shell(); else signIn();
    }
    @Override public void onSaveInstanceState(Bundle state) {
        saveDraft();
        state.putString("job", selectedJob); state.putString("upload", uploadPath); state.putString("export", exportPath);
        state.putString("command", commandDraft); state.putString("script", scriptDraft);
        super.onSaveInstanceState(state);
    }
    private void saveDraft() {
        if (command != null) commandDraft = command.getText().toString();
        if (script != null) scriptDraft = script.getText().toString();
    }
    @Override protected void onResume() { super.onResume(); alive = true; handler.postDelayed(poll, 4000); }
    @Override protected void onPause() { alive = false; handler.removeCallbacks(poll); super.onPause(); }
    @Override protected void onDestroy() { alive = false; handler.removeCallbacksAndMessages(null); executor.shutdownNow(); super.onDestroy(); }
    private final Runnable poll = new Runnable() {
        @Override public void run() {
            if (!alive) return;
            if (api != null && api.signedIn() && screen == 0 && !busy && !polling && command == null) {
                polling = true;
                executor.execute(() -> {
                    try {
                        JSONObject response = api.request("GET", selectedJob == null ? "/api/jobs" : "/api/jobs/" + selectedJob, null);
                        ui(() -> {
                            if (screen == 0) { if (selectedJob == null) renderJobs(response.optJSONArray("jobs")); else renderDetail(response); }
                        });
                    } catch (Exception ignored) { } // Explicit refresh surfaces network errors; polling does not spam toasts.
                    finally { polling = false; }
                });
            }
            handler.postDelayed(this, 4000);
        }
    };
    private void ui(Runnable runnable) { handler.post(() -> { busy = false; if (!isFinishing() && !isDestroyed()) runnable.run(); }); }
    private void task(Task task) {
        if (busy) { toast("Please wait for the current request"); return; }
        busy = true;
        executor.execute(() -> {
            try { task.run(); }
            catch (Exception e) { ui(() -> { toast(e.getMessage() == null ? "Request failed" : e.getMessage()); if (!api.signedIn()) signIn(); }); }
            finally { busy = false; }
        });
    }
    private int dp(float value) { return Math.round(value * getResources().getDisplayMetrics().density); }
    private LinearLayout column() { LinearLayout box = new LinearLayout(this); box.setOrientation(LinearLayout.VERTICAL); return box; }
    private TextView text(String value, int size, int color, boolean bold) {
        TextView t = new TextView(this); t.setText(value); t.setTextSize(size); t.setTextColor(color);
        if (bold) t.setTypeface(Typeface.create("sans-serif-medium", Typeface.NORMAL));
        t.setPadding(0, dp(5), 0, dp(5)); t.setTextIsSelectable(true); return t;
    }
    private GradientDrawable shape(int color, int radius) { GradientDrawable d = new GradientDrawable(); d.setColor(color); d.setCornerRadius(dp(radius)); return d; }
    private LinearLayout card() {
        LinearLayout box = column(); box.setPadding(dp(18), dp(14), dp(18), dp(14)); box.setBackground(shape(Color.WHITE, 22));
        LinearLayout.LayoutParams p = new LinearLayout.LayoutParams(-1, -2); p.setMargins(0, dp(10), 0, dp(4)); box.setLayoutParams(p); return box;
    }
    private Button button(String label, Runnable action) {
        Button b = new Button(this); b.setText(label); b.setAllCaps(false); b.setTextColor(Color.WHITE);
        b.setTextSize(15); b.setMinHeight(dp(48)); b.setBackground(shape(ACCENT, 14));
        LinearLayout.LayoutParams p = new LinearLayout.LayoutParams(-1, -2); p.setMargins(0, dp(10), 0, dp(4)); b.setLayoutParams(p);
        b.setOnClickListener(v -> action.run()); return b;
    }
    private EditText input(String hint, boolean multiline) {
        EditText e = new EditText(this); e.setHint(hint); e.setTextColor(INK); e.setTextSize(15);
        e.setPadding(dp(12), dp(12), dp(12), dp(12)); e.setBackground(shape(0xFFF0F0F4, 12));
        e.setInputType(InputType.TYPE_CLASS_TEXT | (multiline ? InputType.TYPE_TEXT_FLAG_MULTI_LINE | InputType.TYPE_TEXT_FLAG_CAP_SENTENCES : 0));
        if (multiline) { e.setMinLines(3); e.setMaxLines(8); e.setGravity(Gravity.TOP); }
        LinearLayout.LayoutParams p = new LinearLayout.LayoutParams(-1, -2); p.setMargins(0, dp(7), 0, dp(7)); e.setLayoutParams(p); return e;
    }
    private void base() {
        root = column(); root.setBackgroundColor(BG);
        root.setOnApplyWindowInsetsListener((view, insets) -> {
            view.setPadding(dp(22)+insets.getSystemWindowInsetLeft(), insets.getSystemWindowInsetTop(), dp(22)+insets.getSystemWindowInsetRight(), insets.getSystemWindowInsetBottom());
            return insets;
        });
        setContentView(root); root.requestApplyInsets();
    }
    private void signIn() {
        screen = -1; command = script = null; base();
        root.addView(text("GenFlow", 38, INK, true)); root.addView(text("Your production, orchestrated.", 18, MUTED, false));
        LinearLayout c = card(); root.addView(c);
        c.addView(text("Connect your studio", 22, INK, true));
        EditText endpoint = input("HTTPS backend address", false); endpoint.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI); endpoint.setText(api.endpoint()); c.addView(endpoint);
        EditText password = input("GenFlow password", false); password.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD); c.addView(password);
        c.addView(button("Connect securely", () -> {
            String url = endpoint.getText().toString(), secret = password.getText().toString(); password.setText("");
            task(() -> { api.endpoint(url); api.login(secret); ui(this::shell); });
        }));
        root.addView(text("Use the password you created on your server. Google sign-in happens only in your private browser desktop.", 14, MUTED, false));
    }
    private void shell() {
        screen = 0; base(); root.addView(text("GenFlow", 34, INK, true));
        root.addView(text("PRODUCTION STUDIO", 11, MUTED, true));
        ScrollView scroll = new ScrollView(this); scroll.setFillViewport(true); content = column();
        scroll.addView(content); root.addView(scroll, new LinearLayout.LayoutParams(-1, 0, 1));
        navigation = new LinearLayout(this); navigation.setPadding(0, dp(8), 0, dp(8));
        for (int i=0; i<3; i++) {
            final int target = i;
            Button b = button(new String[]{"Episodes", "Projects", "Settings"}[i], () -> navigate(target));
            LinearLayout.LayoutParams p = new LinearLayout.LayoutParams(0, dp(48), 1); p.setMargins(dp(3), 0, dp(3), 0);
            navigation.addView(b, p);
        }
        root.addView(navigation); navigate(0);
    }
    private void navigate(int target) {
        saveDraft(); command = script = null; screen = target; selectedJob = null; content.removeAllViews();
        if (target == 0) refreshJobs(); else if (target == 1) projects(); else settings();
    }
    private void refreshJobs() {
        task(() -> { JSONObject data = api.request("GET", "/api/jobs", null); ui(() -> renderJobs(data.optJSONArray("jobs"))); });
    }
    private void renderJobs(JSONArray jobs) {
        if (screen != 0 || selectedJob != null) return;
        saveDraft(); command = script = null; content.removeAllViews();
        content.addView(text("Make the next episode.", 27, INK, true));
        content.addView(button("＋ New episode", this::newEpisode));
        content.addView(button("Refresh progress", this::refreshJobs));
        if (jobs == null || jobs.length() == 0) content.addView(text("Your episodes will appear here. Start by creating a project and its character bible.", 16, MUTED, false));
        if (jobs != null) for (int i=0; i<jobs.length(); i++) {
            JSONObject job = jobs.optJSONObject(i); if (job == null) continue;
            LinearLayout c = card(); content.addView(c);
            c.addView(text(job.optString("command"), 18, INK, true)); c.addView(text(job.optString("state").toUpperCase(java.util.Locale.ROOT), 12, ACCENT, true));
            if (!job.isNull("error")) c.addView(text(job.optString("error"), 14, MUTED, false));
            c.addView(button("Open episode", () -> { selectedJob = job.optString("id"); loadDetail(); }));
        }
    }
    private void newEpisode() {
        task(() -> {
            JSONArray projects = api.request("GET", "/api/projects", null).getJSONArray("projects");
            ui(() -> {
                if (projects.length() == 0) { toast("Create a project first"); navigate(1); return; }
                final String requestKey = java.util.UUID.randomUUID().toString();
                LinearLayout form = column(); form.setPadding(dp(20), dp(10), dp(20), dp(10));
                String[] labels = new String[projects.length()]; for (int i=0;i<labels.length;i++) labels[i]=projects.optJSONObject(i).optString("title");
                Spinner project = new Spinner(this); project.setAdapter(new ArrayAdapter<>(this, android.R.layout.simple_spinner_dropdown_item, labels)); form.addView(project);
                command = input("Episode 05 complete generate karke final MP4 export kar do.", true); command.setText(commandDraft); form.addView(command);
                script = input("Paste episode script, or leave blank to write it with AI", true); script.setText(scriptDraft); form.addView(script);
                Spinner aspect = new Spinner(this); aspect.setAdapter(new ArrayAdapter<>(this, android.R.layout.simple_spinner_dropdown_item, new String[]{"16:9", "9:16"})); form.addView(aspect);
                EditText attempts = input("Maximum attempts per shot (1–5)", false); attempts.setInputType(InputType.TYPE_CLASS_NUMBER); attempts.setText(R.string.default_max_attempts); form.addView(attempts);
                EditText budget = input("Maximum total generations", false); budget.setInputType(InputType.TYPE_CLASS_NUMBER); budget.setText(R.string.default_generation_budget); form.addView(budget);
                form.addView(text("Only Google Flow generates videos. Each submission can use Google credits. Uncertain QA pauses for review.", 13, MUTED, false));
                ScrollView sc = new ScrollView(this); sc.addView(form);
                AlertDialog dialog = new AlertDialog.Builder(this).setTitle("New GenFlow episode").setView(sc).setNegativeButton("Close", (d,w)->{ saveDraft(); command=script=null; }).setPositiveButton("Queue episode", null).create();
                dialog.setOnShowListener(d -> dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(v -> {
                    saveDraft();
                    try {
                        JSONObject settings = new JSONObject().put("aspect", aspect.getSelectedItem().toString())
                                .put("max_attempts", Integer.parseInt(attempts.getText().toString())).put("max_generations", Integer.parseInt(budget.getText().toString()));
                        JSONObject body = new JSONObject().put("project_id", projects.optJSONObject(project.getSelectedItemPosition()).optString("id"))
                                .put("command", commandDraft).put("script", scriptDraft).put("settings", settings).put("client_request_id", requestKey);
                        task(() -> { JSONObject result = api.request("POST", "/api/jobs", body); ui(() -> {
                            commandDraft=scriptDraft=""; command=script=null; dialog.dismiss(); selectedJob=result.optString("id"); loadDetail();
                        }); });
                    } catch (Exception e) { toast("Enter valid attempt and generation limits"); }
                })); dialog.show();
            });
        });
    }
    private void loadDetail() {
        String id = selectedJob; if (id == null) return;
        task(() -> { JSONObject job = api.request("GET", "/api/jobs/"+id, null); ui(() -> renderDetail(job)); });
    }
    private void renderDetail(JSONObject job) {
        if (screen != 0 || !job.optString("id").equals(selectedJob)) return;
        content.removeAllViews();
        content.addView(button("‹ All episodes", () -> { selectedJob=null; refreshJobs(); }));
        content.addView(text(job.optString("command"), 24, INK, true));
        content.addView(text(job.optString("state").toUpperCase(java.util.Locale.ROOT), 13, ACCENT, true));
        if (!job.isNull("error")) content.addView(text(job.optString("error"), 15, MUTED, false));
        JSONArray shots = job.optJSONArray("shots"); int approved = 0;
        if (shots != null) for (int i=0;i<shots.length();i++) if ("approved".equals(shots.optJSONObject(i).optString("state"))) approved++;
        ProgressBar bar = new ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal); bar.setMax(Math.max(1, shots==null?0:shots.length())); bar.setProgress(approved); content.addView(bar);
        content.addView(text(approved+" / "+(shots==null?0:shots.length())+" shots approved", 13, MUTED, false));
        String state = job.optString("state");
        if (state.equals("completed")) content.addView(button("Save final MP4", () -> saveExport("/api/jobs/"+selectedJob+"/export")));
        else if (state.equals("blocked") || state.equals("failed") || state.equals("cancelled"))
            content.addView(button("Resume episode", () -> action("/api/jobs/"+selectedJob+"/resume", new JSONObject())));
        if (!state.equals("completed") && !state.equals("cancelled")) content.addView(button("Cancel job", () -> confirm("Cancel episode?", "Already submitted Flow generation may still consume credits.", () -> action("/api/jobs/"+selectedJob+"/cancel", new JSONObject()))));
        if (shots != null) for (int i=0;i<shots.length();i++) {
            JSONObject shot = shots.optJSONObject(i); LinearLayout c = card(); content.addView(c);
            c.addView(text("Shot "+(i+1)+"  ·  "+shot.optString("state"), 18, INK, true));
            JSONObject spec=shot.optJSONObject("spec"); if(spec!=null) { c.addView(text(spec.optString("visual"),14,MUTED,false)); c.addView(text(spec.optString("dialogue"),16,INK,false)); }
            c.addView(text("Generation attempts: "+shot.optInt("attempt"), 12, MUTED, false));
            String id = shot.optString("id");
            if (!shot.isNull("path")) c.addView(button("Play clip", () -> play("/api/shots/"+id+"/clip")));
            c.addView(button("Prompt, QA & attempts", () -> { try { new AlertDialog.Builder(this).setTitle("Shot evidence").setMessage(shot.toString(2)).setPositiveButton("Close",null).show(); } catch(Exception ignored){} }));
            if (state.equals("blocked") || state.equals("failed") || state.equals("cancelled")) {
                c.addView(button("Import Google Flow clip", () -> { uploadPath="/api/shots/"+id+"/clip"; pick("video/mp4"); }));
                if (shot.optString("state").equals("review")) c.addView(button("Review & approve", () -> review(id, false, false)));
                c.addView(button("Retry shot", () -> review(id, true, shot.optString("state").equals("submitting"))));
            }
        }
        JSONArray events = job.optJSONArray("events");
        if (events != null) { content.addView(text("Activity", 20, INK, true));
            for(int i=Math.max(0,events.length()-12);i<events.length();i++) content.addView(text(events.optJSONObject(i).optString("kind")+" · "+events.optJSONObject(i).optString("message"),12,MUTED,false)); }
    }
    private void action(String path, JSONObject body) { task(() -> { api.request("POST",path,body); ui(this::loadDetail); }); }
    private void review(String id, boolean retry, boolean uncertainSubmission) {
        EditText note=input("Write what you checked (at least 8 characters)",true);
        String message=retry ? (uncertainSubmission?"Check Flow first. Resubmitting may charge twice for the same shot. Retry limits remain in force.":"A new generation can consume credits. Existing attempts remain in history.") : "Play the clip first. Confirm face, appearance, clothing, voice, exact dialogue, lip sync, sound and continuity. Your review will be recorded.";
        new AlertDialog.Builder(this).setTitle(retry?"Retry shot":"Human QA review").setMessage(message).setView(note)
                .setNegativeButton("Back",null).setPositiveButton(retry?"Confirm retry":"Approve after review",(d,w)->{
                    try { JSONObject body=new JSONObject().put("note",note.getText().toString()).put("acknowledge_duplicate_cost",uncertainSubmission);
                        action("/api/shots/"+id+(retry?"/retry":"/approve"),body); }catch(Exception ignored){}
                }).show();
    }
    private void projects() {
        task(() -> { JSONArray projects=api.request("GET","/api/projects",null).getJSONArray("projects"); ui(()->{
            if(screen!=1)return; content.removeAllViews(); content.addView(text("Character continuity.",27,INK,true));
            content.addView(button("＋ New project",this::createProject));
            for(int i=0;i<projects.length();i++) {
                JSONObject p=projects.optJSONObject(i); LinearLayout c=card(); content.addView(c); c.addView(text(p.optString("title"),21,INK,true));
                try {
                    JSONArray chars = new JSONArray(p.optString("characters"));
                    for (int j=0; j<chars.length(); j++) {
                        JSONObject character = chars.optJSONObject(j);
                        c.addView(text(character.optString("name")+" · "+character.optString("identity"), 14, MUTED, false));
                    }
                    if (chars.length()==0) c.addView(text("Add characters now, or let AI write a reusable bible with the first episode.",14,MUTED,false));
                } catch (Exception ignored) { }
                c.addView(button("Add character", () -> addCharacter(p.optString("id"))));
                c.addView(button("Add character portrait",()->{
                    try { JSONArray chars=new JSONArray(p.optString("characters")); if(chars.length()==0){toast("This project has no saved characters yet");return;}
                        String[] names=new String[chars.length()];for(int j=0;j<names.length;j++)names[j]=chars.optJSONObject(j).optString("name");
                        new AlertDialog.Builder(this).setTitle("Select character · JPEG portrait").setItems(names,(d,which)->{
                            uploadPath="/api/projects/"+p.optString("id")+"/characters/"+which+"/reference";pick("image/jpeg");
                        }).show(); }catch(Exception e){toast("Could not read character bible");}
                }));
            }
        }); });
    }
    private void createProject() {
        EditText title=input("Project title",false);
        new AlertDialog.Builder(this).setTitle("New project").setMessage("Save a project, then add reusable characters and reference portraits.")
                .setView(title).setNegativeButton("Close",null).setPositiveButton("Save",(d,w)->{
            try {JSONObject body=new JSONObject().put("title",title.getText().toString()).put("characters",new JSONArray());
                task(()->{api.request("POST","/api/projects",body);ui(this::projects);});
            }catch(Exception e){toast("Could not save project");}
        }).show();
    }
    private void addCharacter(String projectId) {
        LinearLayout form=column();form.setPadding(dp(20),dp(10),dp(20),dp(10));
        EditText name=input("Character name",false);form.addView(name);
        EditText identity=input("Age, face, skin, hair, body, distinguishing marks",true);form.addView(identity);
        EditText voice=input("Voice, accent and speaking style",true);form.addView(voice);
        EditText clothing=input("Default clothing and accessories",true);form.addView(clothing);
        ScrollView scroll=new ScrollView(this);scroll.addView(form);
        new AlertDialog.Builder(this).setTitle("Lock character identity").setView(scroll).setNegativeButton("Close",null)
                .setPositiveButton("Save character",(d,w)->{
            try {JSONObject body=new JSONObject().put("name",name.getText().toString()).put("identity",identity.getText().toString())
                    .put("voice",voice.getText().toString()).put("default_clothing",clothing.getText().toString());
                task(()->{api.request("POST","/api/projects/"+projectId+"/characters",body);ui(this::projects);});
            }catch(Exception e){toast("Could not save character");}
        }).show();
    }
    private void settings() {
        task(()-> {JSONObject config=api.request("GET","/api/config",null);ui(()->{
            if(screen!=2)return;content.removeAllViews();content.addView(text("Your studio setup.",27,INK,true));
            content.addView(text(api.endpoint(),14,MUTED,false));
            content.addView(text("Planning & analysis API: "+(config.optBoolean("ai_configured")?"configured; live access unverified":"not configured"),15,INK,false));
            content.addView(text("Google Flow · experimental browser integration. Sign in yourself; Google passwords, OTPs and session data stay in that browser.",15,MUTED,false));
            content.addView(button("Open private Flow desktop",()->startActivity(new Intent(Intent.ACTION_VIEW,Uri.parse(api.endpoint()+config.optString("desktop_path"))))));
            content.addView(text("Flow selectors must be calibrated against your live project before automation is enabled. The desktop has a separate password.",14,MUTED,false));
            EditText profile=input("Flow configuration JSON",true);profile.setMinLines(8);
            JSONObject flow=config.optJSONObject("flow");try{profile.setText(flow==null?"{\n  \"enabled\": false,\n  \"project_url\": \"https://flow.google.com/\",\n  \"prompt\": \"CALIBRATE\",\n  \"submit\": \"CALIBRATE\",\n  \"tile\": \"CALIBRATE\",\n  \"download\": \"CALIBRATE\",\n  \"timeout_seconds\": 600\n}":flow.toString(2));}catch(Exception ignored){}
            content.addView(profile);content.addView(button("Save Flow configuration",()->{
                try {JSONObject body=new JSONObject(profile.getText().toString());task(()->{api.request("POST","/api/config/flow",body);ui(()->toast("Saved. Live Flow compatibility is not yet verified."));});}
                catch(Exception e){toast("Invalid configuration JSON");}
            }));
            content.addView(button("Sign out",()->task(()->{try{api.request("POST","/api/logout",new JSONObject());}finally{api.clear();ui(this::signIn);}})));
        });});
    }
    private void play(String path) {
        VideoView video=new VideoView(this);MediaController controls=new MediaController(this);controls.setAnchorView(video);video.setMediaController(controls);
        video.setVideoURI(Uri.parse(api.endpoint()+path),api.videoHeaders());video.setOnPreparedListener(player->video.start());
        video.setOnErrorListener((player,what,extra)->{toast("Video playback failed. Download or retry the clip.");return true;});
        AlertDialog dialog=new AlertDialog.Builder(this).setTitle("GenFlow clip review").setView(video).setPositiveButton("Close",null).create();
        dialog.setOnDismissListener(d->video.stopPlayback());dialog.show();video.getLayoutParams().height=dp(300);
    }
    private void confirm(String title,String message,Runnable yes) { new AlertDialog.Builder(this).setTitle(title).setMessage(message).setNegativeButton("Back",null).setPositiveButton("Confirm",(d,w)->yes.run()).show(); }
    private void pick(String type) { Intent i=new Intent(Intent.ACTION_OPEN_DOCUMENT).setType(type).addCategory(Intent.CATEGORY_OPENABLE);startActivityForResult(i,11); }
    private void saveExport(String path) { exportPath=path;Intent i=new Intent(Intent.ACTION_CREATE_DOCUMENT).setType("video/mp4").addCategory(Intent.CATEGORY_OPENABLE).putExtra(Intent.EXTRA_TITLE,"GenFlow-episode.mp4");startActivityForResult(i,12); }
    @Override protected void onActivityResult(int request,int result,Intent data) {
        super.onActivityResult(request,result,data);if(result!=RESULT_OK||data==null||data.getData()==null)return;
        Uri uri=data.getData();
        if(request==11&&uploadPath!=null) {String path=uploadPath;uploadPath=null;task(()->{
            File temporary=File.createTempFile("GenFlow-upload-",".bin",getCacheDir());
            try { try(InputStream in=getContentResolver().openInputStream(uri);OutputStream out=new FileOutputStream(temporary)){
                if(in==null)throw new IOException("Cannot read selected file");byte[] buffer=new byte[65536];int n;long total=0;
                while((n=in.read(buffer))!=-1){total+=n;if(total>200_000_000)throw new IOException("File exceeds 200 MB");out.write(buffer,0,n);}
            } api.upload(path,temporary,path.endsWith("reference")?"image/jpeg":"video/mp4");ui(()->{toast("Uploaded");if(screen==1)projects();else loadDetail();}); }
            finally {if(!temporary.delete())temporary.deleteOnExit();}
        });}
        if(request==12&&exportPath!=null) {String path=exportPath;exportPath=null;task(()->{
            try(OutputStream out=getContentResolver().openOutputStream(uri,"w")){if(out==null)throw new IOException("Cannot write selected destination");api.download(path,out);}
            ui(()->toast("GenFlow MP4 saved"));
        });}
    }
    private void toast(String message) {Toast.makeText(this,message,Toast.LENGTH_LONG).show();}
}
