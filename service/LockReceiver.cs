// Receiver-only Windows service. SCM is the authenticated control interface.
// No user-supplied command, executable path, INI file or daemon IPC is accepted.
using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;
using System.Security.Principal;
using System.ServiceProcess;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Web.Script.Serialization;

public sealed class LockReceiver : ServiceBase {
    const string ManifestDigest = "__ENGINE_MANIFEST_SHA256__";
    const string ServiceId = "DeskBridgeLockReceiver";
    readonly ManualResetEvent stop = new ManualResetEvent(false);
    readonly object guard = new object();
    Thread worker;
    IntPtr job = IntPtr.Zero;
    Process child;
    string root, engine, owner, localName, serverName, serverPin, localPin;
    int port;
    DateTime lastError = DateTime.MinValue;

    public LockReceiver() { ServiceName = ServiceId; AutoLog = false; CanHandleSessionChangeEvent = true; CanShutdown = true; }
    static string Hash(byte[] data) { using (SHA256 sha = SHA256.Create()) return BitConverter.ToString(sha.ComputeHash(data)).Replace("-", "").ToLowerInvariant(); }
    static void SafePath(string path) {
        for (string p = Path.GetFullPath(path); !String.IsNullOrEmpty(p); p = Path.GetDirectoryName(p))
            if ((File.Exists(p) || Directory.Exists(p)) && (File.GetAttributes(p) & FileAttributes.ReparsePoint) != 0)
                throw new InvalidDataException("Reparse paths are not allowed");
    }
    static byte[] Read(string path, int limit) {
        SafePath(path);
        using (FileStream f = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read)) {
            if (f.Length > limit) throw new InvalidDataException("File size limit");
            byte[] result = new byte[(int)f.Length]; int used = 0;
            while (used < result.Length) { int n = f.Read(result, used, result.Length-used); if (n == 0) throw new EndOfStreamException(); used += n; }
            return result;
        }
    }
    static Dictionary<string,object> Json(byte[] data) {
        return new JavaScriptSerializer { MaxJsonLength = 65536, RecursionLimit = 8 }.Deserialize<Dictionary<string,object>>(Encoding.UTF8.GetString(data));
    }
    static string Field(Dictionary<string,object> cfg, string key, string pattern) {
        string text = cfg[key] as string;
        if (text == null || !Regex.IsMatch(text, pattern)) throw new InvalidDataException("Invalid " + key);
        return text;
    }
    void LoadSnapshot(string profile, string binaries) {
        root = Path.GetFullPath(profile); SafePath(root); SafePath(binaries);
        var cfg = Json(Read(Path.Combine(root, "service.json"), 65536));
        if (cfg.Count != 7 || (int)cfg["schema"] != 1) throw new InvalidDataException("Snapshot schema");
        owner = Field(cfg, "owner_sid", @"\AS-1-5-(?:[0-9]+-)*[0-9]+\z"); new SecurityIdentifier(owner);
        localName = Field(cfg, "local_name", @"\A[A-Za-z][A-Za-z0-9_-]{0,47}\z");
        serverName = Field(cfg, "server_name", @"\A[A-Za-z][A-Za-z0-9_-]{0,47}\z");
        if (String.Equals(localName, serverName, StringComparison.OrdinalIgnoreCase)) throw new InvalidDataException("Separate devices required");
        serverPin = Field(cfg, "server_fp", @"\A[0-9a-f]{64}\z"); localPin = Field(cfg, "local_fp", @"\A[0-9a-f]{64}\z");
        if (localPin == serverPin) throw new InvalidDataException("Separate identities required");
        port = (int)cfg["port"]; if (port < 1024 || port > 65535) throw new InvalidDataException("Invalid port");
        string pem = Encoding.ASCII.GetString(Read(Path.Combine(root, "deskbridge.pem"), 16384));
        Match certText = Regex.Match(pem, "-----BEGIN CERTIFICATE-----([A-Za-z0-9+/=\\r\\n]+)-----END CERTIFICATE-----");
        if (!certText.Success) throw new InvalidDataException("Certificate missing");
        using (var cert = new X509Certificate2(Convert.FromBase64String(certText.Groups[1].Value))) {
            if (Hash(cert.RawData) != localPin || cert.NotBefore.ToUniversalTime() > DateTime.UtcNow || cert.NotAfter.ToUniversalTime() <= DateTime.UtcNow)
                throw new InvalidDataException("Certificate pin or validity");
        }
        byte[] manifestData = Read(Path.Combine(binaries, "EngineManifest.json"), 65536);
        if (Hash(manifestData) != ManifestDigest) throw new InvalidDataException("Engine manifest integrity");
        var manifest = Json(manifestData);
        if (manifest.Count == 0 || manifest.Count > 512) throw new InvalidDataException("Engine file limit");
        string basePath = Path.GetFullPath(Path.Combine(binaries, "engine")) + Path.DirectorySeparatorChar;
        foreach (var item in manifest) {
            if (Path.IsPathRooted(item.Key)) throw new InvalidDataException("Engine path");
            string path = Path.GetFullPath(Path.Combine(basePath, item.Key));
            if (!path.StartsWith(basePath, StringComparison.OrdinalIgnoreCase) || Hash(Read(path, 64*1024*1024)) != (string)item.Value)
                throw new InvalidDataException("Engine file integrity");
        }
        foreach (string file in Directory.GetFiles(basePath, "*", SearchOption.AllDirectories)) {
            SafePath(file);
            if (!manifest.ContainsKey(file.Substring(basePath.Length).Replace('\\', '/'))) throw new InvalidDataException("Unexpected engine file");
        }
        engine = Path.Combine(basePath, "deskflow-1.27.0-win-x64-portable", "deskflow-core.exe");
        if (!manifest.ContainsKey("deskflow-1.27.0-win-x64-portable/deskflow-core.exe")) throw new InvalidDataException("Missing core");
    }
    protected override void OnStart(string[] args) {
        if (WindowsIdentity.GetCurrent().User.Value != "S-1-5-18") throw new InvalidOperationException("LocalSystem service required");
        string binaries = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles), ServiceId);
        if (!String.Equals(Path.GetFullPath(AppDomain.CurrentDomain.BaseDirectory).TrimEnd('\\'), binaries, StringComparison.OrdinalIgnoreCase))
            throw new InvalidOperationException("Protected installation path required");
        LoadSnapshot(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData), ServiceId), binaries);
        stop.Reset(); worker = new Thread(Run) { IsBackground = true }; worker.Start();
    }
    protected override void OnStop() { stop.Set(); StopChild(); if (worker != null) worker.Join(2500); }
    protected override void OnShutdown() { OnStop(); }
    protected override void OnSessionChange(SessionChangeDescription change) { /* 3-second owner check below controls launches. */ }
    void Note(string message, EventLogEntryType type) { try { EventLog.WriteEntry(ServiceId, message, type); } catch (Exception) { /* No secret file fallback. */ } }
    void Error(Exception exc) {
        if ((DateTime.UtcNow-lastError).TotalSeconds >= 30) { Note("Receiver unavailable: " + exc.GetType().Name, EventLogEntryType.Warning); lastError = DateTime.UtcNow; }
    }
    static bool Private(IPAddress a) {
        if (a.AddressFamily != AddressFamily.InterNetwork) return false;
        byte[] b = a.GetAddressBytes(); return b[0] == 10 || (b[0] == 172 && b[1] >= 16 && b[1] <= 31) || (b[0] == 192 && b[1] == 168);
    }
    string Resolve() {
        var addresses = Dns.GetHostAddresses(serverName);
        if (addresses.Length > 16) throw new InvalidDataException("DNS result limit");
        var candidates = new List<string>();
        foreach (var a in addresses) if (a.AddressFamily == AddressFamily.InterNetwork) {
            if (!Private(a)) throw new InvalidDataException("Non-LAN DNS address");
            candidates.Add(a.ToString());
        }
        candidates.Sort(StringComparer.Ordinal); if (candidates.Count == 0) throw new InvalidDataException("No LAN endpoint");
        return candidates[0];
    }
    bool OwnerSession(out uint session) {
        session = WTSGetActiveConsoleSessionId(); if (session == UInt32.MaxValue) return false;
        IntPtr token; if (!WTSQueryUserToken(session, out token)) return false;
        try { using (var user = new WindowsIdentity(token)) return user.User.Value == owner; }
        finally { CloseHandle(token); }
    }
    void Settings(string address) {
        string tls = Path.Combine(root, "tls"); Directory.CreateDirectory(tls);
        File.WriteAllText(Path.Combine(tls, "trusted-servers"), "v2:sha256:"+serverPin+"\n", Encoding.ASCII);
        File.WriteAllText(Path.Combine(tls, "trusted-clients"), "", Encoding.ASCII);
        // Use the protected fixed snapshot, never a user's original INI file.
        string ini = "[core]\ncomputerName="+localName+"\nport="+port+"\ninterface=\nprocessMode=1\nuseHooks=true\nenableEnterCommand=false\nenableExitCommand=false\n"+
            "[client]\nremoteHost="+address+"\nlanguageSync=true\n[security]\ntlsEnabled=true\ncheckPeerFingerprints=true\nkeySize=3072\ncertificate=\""+Path.Combine(root,"deskbridge.pem").Replace('\\','/')+"\"\n"+
            "[server]\nenableClipboard=false\n[log]\nlevel=INFO\ntoFile=false\n[gui]\nenableUpdateCheck=false\n"+
            "[computer_"+localName+"]\nname="+localName+"\n[computer_"+serverName+"]\nname="+serverName+"\n";
        File.WriteAllText(Path.Combine(root,"engine.ini"),ini,new UTF8Encoding(false));
    }
    void Run() {
        string endpoint = null; uint previousSession = UInt32.MaxValue; DateTime nextDns = DateTime.MinValue;
        int failures = 0; DateTime stable = DateTime.UtcNow;
        bool faulted = false;
        try {
            while (!stop.WaitOne(3000)) {
                bool attempted = false;
                try {
                    uint session;
                    if (!OwnerSession(out session)) { StopChild(); endpoint=null; previousSession=UInt32.MaxValue; continue; }
                    string current = endpoint;
                    if (current == null || DateTime.UtcNow >= nextDns) { current = Resolve(); nextDns=DateTime.UtcNow.AddSeconds(15); }
                    bool alive; lock (guard) alive = child != null && !child.HasExited;
                    if (alive && (DateTime.UtcNow-stable).TotalSeconds > 60) failures=0;
                    if (!alive || current != endpoint || previousSession != session) {
                        if (!alive && failures >= 3) { Note("Recovery limit reached; administrator restart required.",EventLogEntryType.Error); faulted=true; stop.Set(); break; }
                        if (!alive) { failures++; attempted=true; }
                        StopChild(); if (stop.WaitOne(0)) break;
                        Settings(current); Launch(session); endpoint=current; previousSession=session; stable=DateTime.UtcNow;
                    }
                } catch (Exception exc) { Error(exc); if (child == null && !attempted) failures++; if (failures >= 3 && child == null) { faulted=true; stop.Set(); break; } }
            }
        } finally { StopChild(); if (faulted) ThreadPool.QueueUserWorkItem(delegate { Stop(); }); }
    }
    void Launch(uint session) {
        // Duplicate this service's SYSTEM token into the explicitly authorized
        // user's console session. No winlogon process token is opened.
        lock (guard) {
            IntPtr source=IntPtr.Zero, token=IntPtr.Zero, env=IntPtr.Zero; PROCESS_INFORMATION pi=new PROCESS_INFORMATION();
            try {
                if (!OpenProcessToken(GetCurrentProcess(),0x0002|0x0008,out source) || !DuplicateTokenEx(source,0xF01FF,IntPtr.Zero,2,1,out token)) throw new Win32Exception();
                if (!SetTokenInformation(token,12,ref session,4)) throw new Win32Exception();
                uint ui=1; if (!SetTokenInformation(token,26,ref ui,4)) throw new Win32Exception();
                if (!CreateEnvironmentBlock(out env,token,false)) throw new Win32Exception();
                job=CreateJobObject(IntPtr.Zero,null); if (job==IntPtr.Zero) throw new Win32Exception();
                JOBOBJECT_EXTENDED_LIMIT_INFORMATION limit=new JOBOBJECT_EXTENDED_LIMIT_INFORMATION(); limit.BasicLimitInformation.LimitFlags=0x2000;
                if (!SetInformationJobObject(job,9,ref limit,Marshal.SizeOf(limit))) throw new Win32Exception();
                STARTUPINFO si=new STARTUPINFO(); si.cb=Marshal.SizeOf(si); si.lpDesktop="WinSta0\\Default";
                var command=new StringBuilder("\""+engine+"\" client --settings \""+Path.Combine(root,"engine.ini")+"\"");
                uint currentSession; if (!OwnerSession(out currentSession) || currentSession != session) throw new InvalidOperationException("Owner session changed");
                if (!CreateProcessAsUser(token,engine,command,IntPtr.Zero,IntPtr.Zero,false,0x00000400|0x08000000|0x00000004,env,Path.GetDirectoryName(engine),ref si,out pi)) throw new Win32Exception();
                if (!AssignProcessToJobObject(job,pi.hProcess)) throw new Win32Exception();
                child=Process.GetProcessById((int)pi.dwProcessId);
                if (!OwnerSession(out currentSession) || currentSession != session) throw new InvalidOperationException("Owner session changed");
                if (ResumeThread(pi.hThread)==UInt32.MaxValue) throw new Win32Exception();
                Note("Locked-screen receiver started in authorized console session.",EventLogEntryType.Information);
            } catch { if (pi.hProcess!=IntPtr.Zero) TerminateProcess(pi.hProcess,1); StopChild(); throw; }
            finally { if(pi.hThread!=IntPtr.Zero) CloseHandle(pi.hThread); if(pi.hProcess!=IntPtr.Zero) CloseHandle(pi.hProcess); if(env!=IntPtr.Zero) DestroyEnvironmentBlock(env); if(token!=IntPtr.Zero) CloseHandle(token); if(source!=IntPtr.Zero) CloseHandle(source); }
        }
    }
    void StopChild() { lock (guard) { if(job!=IntPtr.Zero) { CloseHandle(job); job=IntPtr.Zero; } if(child!=null) { child.Dispose(); child=null; } } }
    public static int Main(string[] args) {
        try {
            if(args.Length==3 && args[0]=="--verify-snapshot") { var test=new LockReceiver(); test.LoadSnapshot(args[1],args[2]); Console.WriteLine("Snapshot, identity and engine integrity verified."); return 0; }
            ServiceBase.Run(new LockReceiver()); return 0;
        } catch(Exception exc) { Console.Error.WriteLine(exc.GetType().Name+": "+exc.Message); return 1; }
    }
    [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Unicode)] struct STARTUPINFO { public int cb; public string lpReserved,lpDesktop,lpTitle; public uint dwX,dwY,dwXSize,dwYSize,dwXCountChars,dwYCountChars,dwFillAttribute,dwFlags; public short wShowWindow,cbReserved2; public IntPtr lpReserved2,hStdInput,hStdOutput,hStdError; }
    [StructLayout(LayoutKind.Sequential)] struct PROCESS_INFORMATION { public IntPtr hProcess,hThread; public uint dwProcessId,dwThreadId; }
    [StructLayout(LayoutKind.Sequential)] struct JOBOBJECT_BASIC_LIMIT_INFORMATION { public long PerProcessUserTimeLimit,PerJobUserTimeLimit; public uint LimitFlags; public UIntPtr MinimumWorkingSetSize,MaximumWorkingSetSize; public uint ActiveProcessLimit; public UIntPtr Affinity; public uint PriorityClass,SchedulingClass; }
    [StructLayout(LayoutKind.Sequential)] struct IO_COUNTERS { public ulong ReadOperationCount,WriteOperationCount,OtherOperationCount,ReadTransferCount,WriteTransferCount,OtherTransferCount; }
    [StructLayout(LayoutKind.Sequential)] struct JOBOBJECT_EXTENDED_LIMIT_INFORMATION { public JOBOBJECT_BASIC_LIMIT_INFORMATION BasicLimitInformation; public IO_COUNTERS IoInfo; public UIntPtr ProcessMemoryLimit,JobMemoryLimit,PeakProcessMemoryUsed,PeakJobMemoryUsed; }
    [DllImport("kernel32.dll")] static extern IntPtr GetCurrentProcess();
    [DllImport("kernel32.dll",SetLastError=true)] static extern bool CloseHandle(IntPtr h);
    [DllImport("kernel32.dll",SetLastError=true,CharSet=CharSet.Unicode)] static extern IntPtr CreateJobObject(IntPtr sa,string name);
    [DllImport("kernel32.dll",SetLastError=true)] static extern bool SetInformationJobObject(IntPtr h,int cls,ref JOBOBJECT_EXTENDED_LIMIT_INFORMATION info,int size);
    [DllImport("kernel32.dll",SetLastError=true)] static extern bool AssignProcessToJobObject(IntPtr job,IntPtr process);
    [DllImport("kernel32.dll",SetLastError=true)] static extern bool TerminateProcess(IntPtr h,uint code);
    [DllImport("kernel32.dll",SetLastError=true)] static extern uint ResumeThread(IntPtr h);
    [DllImport("kernel32.dll")] static extern uint WTSGetActiveConsoleSessionId();
    [DllImport("wtsapi32.dll",SetLastError=true)] static extern bool WTSQueryUserToken(uint id,out IntPtr token);
    [DllImport("advapi32.dll",SetLastError=true)] static extern bool OpenProcessToken(IntPtr process,uint access,out IntPtr token);
    [DllImport("advapi32.dll",SetLastError=true)] static extern bool DuplicateTokenEx(IntPtr source,uint access,IntPtr sa,int level,int type,out IntPtr token);
    [DllImport("advapi32.dll",SetLastError=true)] static extern bool SetTokenInformation(IntPtr token,int cls,ref uint value,int size);
    [DllImport("userenv.dll",SetLastError=true)] static extern bool CreateEnvironmentBlock(out IntPtr env,IntPtr token,bool inherit);
    [DllImport("userenv.dll",SetLastError=true)] static extern bool DestroyEnvironmentBlock(IntPtr env);
    [DllImport("advapi32.dll",SetLastError=true,CharSet=CharSet.Unicode)] static extern bool CreateProcessAsUser(IntPtr token,string app,StringBuilder command,IntPtr psa,IntPtr tsa,bool inherit,uint flags,IntPtr env,string cwd,ref STARTUPINFO si,out PROCESS_INFORMATION pi);
}
