import React, { useState, useEffect, useRef } from 'react';
import { 
  Play, 
  Pause, 
  Square, 
  Home, 
  ChevronUp, 
  ChevronDown, 
  ChevronLeft, 
  ChevronRight, 
  Lock, 
  Unlock, 
  Settings, 
  Bell, 
  HelpCircle, 
  Layers, 
  Activity, 
  Camera, 
  Terminal, 
  Cpu, 
  Flame, 
  Droplet, 
  Sliders, 
  Grid3X3, 
  Upload, 
  Undo,
  FileCheck2,
  FileCode2,
  Database
} from 'lucide-react';

// Sample CAD Models defined via parametric rendering paths so they are fully lightweight & SVG based!
interface CADModel {
  name: string;
  filename: string;
  dim: string;
  dpi: number;
  layers: number;
  drawPaths: (slice: number, threshold: number) => React.ReactNode;
}

export default function App() {
  // Define standard layouts & scaling
  const containerRef = useRef<HTMLDivElement>(null);
  const [scale, setScale] = useState(1);
  const [activeTab, setActiveTab] = useState<'manufacturing' | 'monitoring' | 'maintenance' | 'logs'>('manufacturing');

  // Interactive Machine States
  const [isPrinting, setIsPrinting] = useState(false);
  const [isPaused, setIsPaused] = useState(false);
  const [currentLayer, setCurrentLayer] = useState(142);
  const [totalLayers, setTotalLayers] = useState(450);
  const [threshold, setThreshold] = useState(128);
  const [layerThickness, setLayerThickness] = useState(0.100);
  const [overfeedRatio, setOverfeedRatio] = useState(1.2);
  
  // Coordinates & Telemetry (Simulating standard GRBL signals)
  const [coords, setCoords] = useState({ x: 142.005, y: 88.421, feed: 12.000, build: -1.420 });
  const [headTemp, setHeadTemp] = useState(42);
  const [vacuum, setVacuum] = useState(-4.2);
  const [isEmergencyUnlocked, setIsEmergencyUnlocked] = useState(true);
  const [comPort, setComPort] = useState('COM3 - Main');
  const [isComConnected, setIsComConnected] = useState(true);
  
  // Simulation animations
  const [recoaterPosition, setRecoaterPosition] = useState(-20); // -20% is offscreen left, 120% is offscreen right
  const [recoaterDirection, setRecoaterDirection] = useState<'none' | 'forward' | 'backward'>('none');
  const [carriagePosition, setCarriagePosition] = useState(50); // 0 to 100% of printing stroke
  const [carriageDirection, setCarriageDirection] = useState<'left' | 'right' | 'none'>('none');
  const [isSprayingCheck, setIsSprayingCheck] = useState(false);
  const [isPreheating, setIsPreheating] = useState(false);
  const [selectedModelIdx, setSelectedModelIdx] = useState(0);

  // Nozzle Grid: representing 300 nozzles grouped into 10 interactive hardware chips
  // Each chip monitors 30 nozzles. Clicking toggles block state, changing total active.
  const [nozzleChips, setNozzleChips] = useState<boolean[]>([
    true, true, true, false, true, true, true, true, false, true
  ]);

  // Port and Connection state mappings for PyQt HMI components
  const [motionPort, setMotionPort] = useState("COM11");
  const [isMotionConnected, setIsMotionConnected] = useState(false);
  const [inkjetPort, setInkjetPort] = useState("COM6");
  const [isInkjetConnected, setIsInkjetConnected] = useState(false);
  const [layerThicknessVal, setLayerThicknessVal] = useState(2); // Maps to layerThickness: 1 to 20 slider
  const [overfeedVal, setOverfeedVal] = useState(6); // Maps to overfeedRatio: 0 to 14 slider
  const [inkjetDensityVal, setInkjetDensityVal] = useState(10); // Inkjet fluid target density slider
  const [startLayerSpinbox, setStartLayerSpinbox] = useState(1);
  const [selectedDpi, setSelectedDpi] = useState("300 DPI");
  const [selectedSweep, setSelectedSweep] = useState("2 Sweeps");
  const [selectedMode, setSelectedMode] = useState("3D Printing");
  const [inkjetTestStateValue, setInkjetTestStateValue] = useState("STATUS: IDLE");
  const [fileDimensionsInput, setFileDimensionsInput] = useState("X: 200.0, Y: 200.0 mm");

  // Rich log system state instead of static layout
  const [logsList, setLogsList] = useState<string[]>([
    "[HMI] SYSTEM COMMUNICATOR ONLINE -- BAUD SPEED 115200",
    "[COM3] Sending command: $$ -- GRBL SETTINGS PARSER",
    "$0=10 (Step pulse time, microseconds)",
    "$1=25 (Step idle delay, milliseconds)",
    "$100=200.000 (X-axis travel resolution, step/mm)",
    "$101=200.000 (Y-axis travel resolution, step/mm)",
    "$102=1000.000 (Z-axis travel resolution, step/mm)",
    "[GRBL] ok - Status received: IDLE <Wpos: 142.005, 88.421, -1.420>"
  ]);

  const addLog = (text: string) => {
    setLogsList(prev => {
      const copy = [...prev];
      if (copy.length > 60) copy.shift();
      return [...copy, `[${new Date().toLocaleTimeString()}] ${text}`];
    });
  };

  // Handle proportional scale relative to window size (Qt 'resizeEvent' web equivalent)
  useEffect(() => {
    if (!containerRef.current) return;
    const observer = new ResizeObserver((entries) => {
      for (let entry of entries) {
        const width = entry.contentRect.width;
        const computedScale = Math.max(0.65, Math.min(1.25, width / 1440));
        setScale(computedScale);
      }
    });
    observer.observe(containerRef.current);
    return () => observer.disconnect();
  }, []);

  // Calculate Active Nozzles based on chips state
  const totalNozzles = 300;
  const activeNozzlesCount = nozzleChips.reduce((sum, active) => sum + (active ? 30 : 17), 0);

  // Sliced designs
  const cadModels: CADModel[] = [
    {
      name: "Enclosure Manifold v3",
      filename: "BJT_ENCL_V3.PRN",
      dim: "2048 x 2048 PX",
      dpi: 300,
      layers: 450,
      drawPaths: (slice: number, thresh: number) => {
        const radiusMultiplier = Math.max(0.2, 1.8 - (thresh / 128));
        const opacityMultiplier = Math.max(0.1, 1.2 - Math.abs(thresh - 128)/255);
        return (
          <g stroke="#ffffff" fill="none" strokeWidth="1.5">
            {/* Outer wireframe shell */}
            <path d="M 60 70 L 160 50 L 160 170 L 60 190 Z" opacity={0.3} />
            <path d="M 60 70 L 60 190 M 160 50 L 160 170" opacity={0.3} />
            {/* Core Cylindrical internal chamber */}
            <circle cx="110" cy="115" r={32 * radiusMultiplier} stroke="#3b82f6" strokeWidth={thresh < 80 ? "3" : thresh > 180 ? "0.8" : "1.8"} />
            <circle cx="110" cy="115" r={16 * radiusMultiplier} stroke="#60a5fa" strokeDasharray="3 3" />
            
            {/* Intricate vertical heat ribs */}
            <line x1="75" y1="95" x2="145" y2="75" stroke="#93c5fd" opacity={opacityMultiplier} />
            <line x1="75" y1="115" x2="145" y2="95" stroke="#93c5fd" opacity={opacityMultiplier} />
            <line x1="75" y1="135" x2="145" y2="115" stroke="#93c5fd" opacity={opacityMultiplier} />
            <line x1="75" y1="155" x2="145" y2="135" stroke="#93c5fd" opacity={opacityMultiplier} />
            
            {/* Mechanical top bolts */}
            <circle cx="110" cy="50" r="4" stroke="#ffffff" />
            <circle cx="60" cy="70" r="4" stroke="#ffffff" />
            <circle cx="160" cy="50" r="4" stroke="#ffffff" />
            
            {/* Fluid intake port indicator */}
            <ellipse cx="110" cy="165" rx="20" ry="8" stroke="#3b82f6" />
            <ellipse cx="110" cy="165" rx="10" ry="4" stroke="#60a5fa" />
          </g>
        );
      }
    },
    {
      name: "Planetary Gear Ring",
      filename: "GEAR_PLN_V2.PRN",
      dim: "3000 x 3000 PX",
      dpi: 400,
      layers: 280,
      drawPaths: (slice: number, thresh: number) => {
        const ratio = 1 + (128 - thresh) / 256;
        return (
          <g stroke="#ffffff" fill="none" strokeWidth="1.5">
            {/* Outer gear ring teeth */}
            <circle cx="110" cy="115" r={50 * ratio} stroke="#60a5fa" strokeDasharray="6 3" strokeWidth="2" />
            <circle cx="110" cy="115" r={45 * ratio} stroke="#3b82f6" />
            
            {/* Sun Gear Core */}
            <circle cx="110" cy="115" r={15 * ratio} stroke="#93c5fd" />
            <circle cx="110" cy="115" r={10 * ratio} stroke="#3b82f6" strokeDasharray="2 2" />
            
            {/* Planitary gears around center */}
            {[0, 120, 240].map((angle, idx) => {
              const rad = (angle * Math.PI) / 180;
              const px = 110 + Math.cos(rad) * 30 * ratio;
              const py = 115 + Math.sin(rad) * 30 * ratio;
              return (
                <g key={idx}>
                  <circle cx={px} cy={py} r={9 * ratio} stroke="#ffffff" strokeDasharray="3 1" />
                  <circle cx={px} cy={py} r={3} stroke="#3b82f6" fill="#3b82f6" opacity={0.6} />
                </g>
              );
            })}
            
            {/* Directional markers */}
            <line x1="110" y1="30" x2="110" y2="200" stroke="#4b5563" strokeDasharray="5 5" opacity={0.4} />
            <line x1="25" y1="115" x2="195" y2="115" stroke="#4b5563" strokeDasharray="5 5" opacity={0.4} />
          </g>
        );
      }
    },
    {
      name: "Turbine Adapter Nozzle",
      filename: "TURB_NZL_V1.PRN",
      dim: "1024 x 1024 PX",
      dpi: 150,
      layers: 620,
      drawPaths: (slice: number, thresh: number) => {
        const expansion = Math.max(0.4, 2.0 - (thresh / 100));
        return (
          <g stroke="#ffffff" fill="none" strokeWidth="1.5">
            {/* Nozzle convergent throat outline */}
            <path d={`M 50 50 Q 110 80 110 120 Q 110 160 170 190`} stroke="#ffffff" strokeWidth="2.5" />
            <path d={`M 170 50 Q 110 80 110 120 Q 110 160 50 190`} stroke="#ffffff" strokeWidth="2.5" />
            
            {/* Dynamic expansion gas contours */}
            <path d={`M 80 50 Q 110 80 110 120 Q 110 160 140 190`} stroke="#3b82f6" opacity={0.7} strokeWidth="1.2" />
            <path d={`M 140 50 Q 110 80 110 120 Q 110 160 80 190`} stroke="#3b82f6" opacity={0.7} strokeWidth="1.2" />
            
            {/* Throat shock waves */}
            <line x1="110" y1="120" x2="70" y2="150" stroke="#93c5fd" strokeDasharray="2 2" opacity={expansion} />
            <line x1="110" y1="120" x2="150" y2="150" stroke="#93c5fd" strokeDasharray="2 2" opacity={expansion} />
            
            <circle cx="110" cy="120" r="6" stroke="#ef4444" fill="#ef4444" opacity={0.8} />
            
            {/* Dimension brackets */}
            <line x1="35" y1="50" x2="185" y2="50" stroke="#6b7280" opacity={0.5} />
            <line x1="35" y1="190" x2="185" y2="190" stroke="#6b7280" opacity={0.5} />
          </g>
        );
      }
    }
  ];

  const activeModel = cadModels[selectedModelIdx];

  // Simulated background printing loop
  useEffect(() => {
    let interval: NodeJS.Timeout;

    if (isPrinting && !isPaused) {
      addLog(`[SYSTEM] Starting print pass for layer ${currentLayer}...`);
      interval = setInterval(() => {
        // Increment layers inside simulated limits
        setCurrentLayer(prev => {
          if (prev >= activeModel.layers) {
            setIsPrinting(false);
            addLog("[SYSTEM] Print job completed successfully! Re-centering gantry...");
            return activeModel.layers;
          }
          const nextLayer = prev + 1;
          
          // Trigger spreader roller sweeping animation on layer increment
          // Spreader triggers: Recoater sweeps from left to right (0 to 100), printhead fires, then sweeps back!
          triggerRecoaterCycle();
          addLog(`[ROLLER] Automatic layer recoat sweep activated for layer ${nextLayer}.`);
          return nextLayer;
        });

        // Add subtle telemetry fluctuations (vacuum, temp, axes)
        setVacuum(v => +(v + (Math.random() - 0.5) * 0.15).toFixed(2));
        setHeadTemp(t => {
          const target = isPreheating ? 45 : 42;
          const delta = target - t;
          return +(t + delta * 0.2 + (Math.random() - 0.5) * 0.2).toFixed(1);
        });

        // Slowly modify coords values to show motor movement simulation
        setCoords(prev => {
          const nx = +(110 + (Math.random() - 0.5) * 80).toFixed(3);
          const ny = +(100 + (Math.random() - 0.5) * 60).toFixed(3);
          
          addLog(`[GCODE] G1 X${nx} Y${ny} F1200 -- Execution Step OK`);
          addLog(`[HP45] Firing printhead nozzle elements at target density ${inkjetDensityVal}%`);
          
          return {
            x: nx,
            y: ny,
            feed: prev.feed,
            build: +(-1.420 - (currentLayer / activeModel.layers) * 1.5).toFixed(3)
          };
        });

      }, 3500); // Trigger physical event block periodically
    }

    return () => clearInterval(interval);
  }, [isPrinting, isPaused, currentLayer, selectedModelIdx, isPreheating, inkjetDensityVal]);

  // Spreader roller animation sequence trigger
  const triggerRecoaterCycle = () => {
    setRecoaterDirection('forward');
    setRecoaterPosition(-20);
  };

  // Recoater positions transition physics
  useEffect(() => {
    let animFrame: number;
    const updatePhysics = () => {
      // Forward Carriage Move
      if (recoaterDirection === 'forward') {
        setRecoaterPosition(p => {
          if (p >= 120) {
            // Once reached right end, trigger carriage printhead pass, then return
            setRecoaterDirection('backward');
            // Mock printing spray action
            setIsSprayingCheck(true);
            return 120;
          }
          return p + 2;
        });
      } else if (recoaterDirection === 'backward') {
        setIsSprayingCheck(false);
        setRecoaterPosition(p => {
          if (p <= -20) {
            setRecoaterDirection('none');
            return -20;
          }
          return p - 3; // Sweeping backward is faster
        });
      }
      
      // Simulate nozzle jetting carriage shaking left to right
      if (isSprayingCheck) {
        setCarriagePosition(p => {
          const delta = Math.sin(Date.now() / 80) * 12 + 50;
          return delta;
        });
      }

      if (recoaterDirection !== 'none' || isSprayingCheck) {
        animFrame = requestAnimationFrame(updatePhysics);
      }
    };

    if (recoaterDirection !== 'none') {
      animFrame = requestAnimationFrame(updatePhysics);
    }

    return () => cancelAnimationFrame(animFrame);
  }, [recoaterDirection, isSprayingCheck]);

  // Print button action
  const handlePrint = () => {
    if (!isEmergencyUnlocked) {
      addLog("[ERROR] Machine safety interlock shield is LOCKED. Unlock hatch first!");
      return;
    }
    addLog("[SYSTEM] Started physical printhead cycle... and feeding GCODE sequence lines");
    setIsPrinting(true);
    setIsPaused(false);
  };

  // Pause action
  const handlePause = () => {
    setIsPaused(curr => {
      const target = !curr;
      addLog(`[SYSTEM] Print execution state: ${target ? 'PAUSED' : 'RESUMED'}. Gcode motors buffer updated.`);
      return target;
    });
  };

  // Abort action
  const handleAbort = () => {
    addLog("[WARNING] Emergency cancel received. Halting Gantry motors... Venting nozzle vacuums.");
    setIsPrinting(false);
    setIsPaused(false);
    setCurrentLayer(1);
    setCoords(c => ({ ...c, x: 0.0, y: 0.0 }));
  };

  // Jog Operations (X & Y Axis stepper simulation)
  const handleJog = (axis: 'X' | 'Y', direction: '+' | '-') => {
    setCoords(prev => {
      const delta = direction === '+' ? 1.5 : -1.5;
      const newX = axis === 'X' ? +(prev.x + delta).toFixed(3) : prev.x;
      const newY = axis === 'Y' ? +(prev.y + delta).toFixed(3) : prev.y;
      addLog(`[MANUAL JOG] Moving mechanical ${axis} axis to point ${axis === 'X' ? newX : newY} mm... ok.`);
      return { ...prev, x: newX, y: newY };
    });
  };

  const handleHomeAll = () => {
    addLog("[GRBL] Sending command: $H -- HOMING MACHINERY AXES (X & Y)");
    setCoords(prev => ({ ...prev, x: 0.000, y: 0.000 }));
  };

  const handlePistonAdjust = (piston: 'feed' | 'build', op: 'up' | 'dn') => {
    setCoords(prev => {
      const step = op === 'up' ? 0.05 : -0.05;
      const val = piston === 'feed' ? prev.feed + step : prev.build + step;
      addLog(`[PISTON ADJUST] Stepping ${piston} table ${op.toUpperCase()} by ${Math.abs(step)}mm. Target: ${val.toFixed(3)}mm.`);
      if (piston === 'feed') {
        return { ...prev, feed: +val.toFixed(3) };
      } else {
        return { ...prev, build: +val.toFixed(3) };
      }
    });
  };

  // Trigger utilities
  const handleUtilityAction = (action: string) => {
    if (action === 'Preheat') {
      setIsPreheating(curr => !curr);
    } else if (action === 'Prime') {
      // Simulate quick squirt
      setIsSprayingCheck(true);
      setTimeout(() => setIsSprayingCheck(false), 800);
    } else if (action === 'Test Head') {
      // Flash chips colors representing active nozzles
      setNozzleChips([true, true, true, true, true, true, true, true, true, true]);
      setTimeout(() => {
        setNozzleChips([true, true, true, false, true, true, true, true, false, true]);
      }, 1500);
    } else if (action === 'Purge') {
      setIsSprayingCheck(true);
      setTimeout(() => setIsSprayingCheck(false), 500);
    }
  };

  const toggleNozzleChip = (idx: number) => {
    setNozzleChips(prev => {
      const copy = [...prev];
      copy[idx] = !copy[idx];
      return copy;
    });
  };

  const currentPercent = Math.min(100, Math.floor((currentLayer / activeModel.layers) * 100));

  return (
    <div 
      id="main-applet-root"
      ref={containerRef}
      className="flex h-screen w-screen bg-neutral-100 font-sans text-neutral-900 select-none overflow-hidden"
    >
      {/* PERSISTENT LEFT NAVIGATION RAIL - 64px width */}
      <div 
        id="side_navigation_rail" 
        className="w-16 h-full bg-neutral-900 flex flex-col items-center justify-between py-4 z-40 border-r border-neutral-800"
      >
        <div className="flex flex-col items-center gap-6 w-full">
          {/* Logo / Brand header */}
          <div className="w-10 h-10 rounded-lg bg-primary-blue flex items-center justify-center text-white shadow-md animate-pulse">
            <Cpu className="w-6 h-6 stroke-[2]" />
          </div>

          <div className="flex flex-col gap-3 w-full px-2" style={{ fontSize: `${scale * 100}%` }}>
            <button 
              id="nav_btn_manufacturing"
              onClick={() => setActiveTab('manufacturing')}
              className={`w-12 h-12 rounded-lg flex items-center justify-center transition-all ${activeTab === 'manufacturing' ? 'bg-primary-blue text-white shadow-lg' : 'text-neutral-400 hover:text-white hover:bg-neutral-800'}`}
              title="Manufacturing Layout"
            >
              <Grid3X3 className="w-5 h-5" />
            </button>

            <button 
              id="nav_btn_sliders"
              onClick={() => setActiveTab('monitoring')}
              className={`w-12 h-12 rounded-lg flex items-center justify-center transition-all ${activeTab === 'monitoring' ? 'bg-primary-blue text-white shadow-lg' : 'text-neutral-400 hover:text-white hover:bg-neutral-800'}`}
              title="Telemetry Monitoring"
            >
              <Sliders className="w-5 h-5" />
            </button>

            <button 
              id="nav_btn_maintenance"
              onClick={() => setActiveTab('maintenance')}
              className={`w-12 h-12 rounded-lg flex items-center justify-center transition-all ${activeTab === 'maintenance' ? 'bg-primary-blue text-white shadow-lg' : 'text-neutral-400 hover:text-white hover:bg-neutral-800'}`}
              title="System Diagnostics"
            >
              <Activity className="w-5 h-5" />
            </button>

            <button 
              id="nav_btn_logs"
              onClick={() => setActiveTab('logs')}
              className={`w-12 h-12 rounded-lg flex items-center justify-center transition-all ${activeTab === 'logs' ? 'bg-primary-blue text-white shadow-lg' : 'text-neutral-400 hover:text-white hover:bg-neutral-800'}`}
              title="Real-Time Logs"
            >
              <Terminal className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* BOTTOM RED HARD STOP ACCENT TRIGGER */}
        <div className="w-full px-2">
          <button 
            id="emergency-hardware-interlock"
            onClick={() => setIsEmergencyUnlocked(c => !c)}
            className={`w-12 h-12 rounded-lg flex items-center justify-center transition-all ${!isEmergencyUnlocked ? 'bg-red-600 text-white animate-bounce' : 'bg-neutral-800 hover:bg-red-950 text-red-500'}`}
            title="Toggle Safety Interlock Shield"
          >
            <Lock className="w-5 h-5 stroke-[2.5]" />
          </button>
        </div>
      </div>

      {/* CORE WORKSPACE PANEL CONTAINER */}
      <div 
        id="core_hmi_workspace_wrapper" 
        className="flex-1 flex flex-col h-full overflow-hidden bg-neutral-100"
        style={{ transformOrigin: 'top left', fontSize: `${scale * 100}%` }}
      >
        {/* TOP STATUS HEADER BAR */}
        <header 
          id="hmi_global_top_bar" 
          className="h-16 w-full bg-white border-b border-neutral-200 flex items-center justify-between px-6 z-10"
        >
          <div className="flex items-center gap-3">
            <h1 className="text-xl font-bold tracking-tight text-neutral-900 select-text">
              Binder Jet System Console
            </h1>
            <span className="h-4 w-px bg-neutral-300"></span>
            <p className="text-xs font-mono text-neutral-500 bg-neutral-100 px-2 py-1 rounded">
              NODE_004: {isComConnected ? 'ACTIVE' : 'OFFLINE'}
            </p>
          </div>

          {/* Tab Navigation - Restyled */}
          <nav className="flex h-full items-center gap-1">
            {(['manufacturing', 'monitoring', 'maintenance', 'logs'] as const).map((tab) => (
              <button
                key={tab}
                onClick={() => setActiveTab(tab)}
                className={`px-4 h-full border-b-2 text-sm font-medium transition-all flex items-center gap-2 ${
                  activeTab === tab
                    ? 'border-primary-blue text-primary-blue'
                    : 'border-transparent text-neutral-500 hover:text-neutral-900'
                }`}
              >
                {tab === 'manufacturing' && <Grid3X3 className="w-4 h-4" />}
                {tab === 'monitoring' && <Sliders className="w-4 h-4" />}
                {tab === 'maintenance' && <Activity className="w-4 h-4" />}
                {tab === 'logs' && <Terminal className="w-4 h-4" />}
                {tab.charAt(0).toUpperCase() + tab.slice(1)}
              </button>
            ))}
          </nav>

          <div className="flex items-center gap-4">
            {/* Quick Status Buttons */}
            <div className="flex gap-2">
              <button 
                id="header_quick_start"
                onClick={handlePrint}
                disabled={!isEmergencyUnlocked || isPrinting}
                className="px-3 py-1.5 rounded bg-primary-blue hover:bg-primary-blue-hover text-white text-xs font-semibold flex items-center gap-1.5 disabled:opacity-40 shadow-sm"
              >
                <Play className="w-3.5 h-3.5 fill-white" /> Start Job
              </button>
              <button 
                id="header_quick_pause"
                onClick={handlePause}
                disabled={!isPrinting}
                className="px-3 py-1.5 rounded bg-neutral-200 hover:bg-neutral-300 text-neutral-800 text-xs font-semibold flex items-center gap-1.5 disabled:opacity-40 border border-neutral-300"
              >
                <Pause className="w-3.5 h-3.5 fill-neutral-800" /> Pause
              </button>
            </div>

            <span className="h-5 w-px bg-neutral-200"></span>

            {/* Utility Indicators */}
            <div className="flex items-center gap-2 text-neutral-500">
              <button className="p-1.5 hover:bg-neutral-100 rounded-full text-neutral-600 relative">
                <Bell className="w-4 h-4" />
                <span className="absolute top-1 right-1 w-2 h-2 rounded-full bg-red-500 animate-ping"></span>
              </button>
              <button className="p-1.5 hover:bg-neutral-100 rounded-full text-neutral-600">
                <Settings className="w-4 h-4" />
              </button>
              <button className="p-1.5 hover:bg-neutral-100 rounded-full text-neutral-600">
                <HelpCircle className="w-4 h-4" />
              </button>
            </div>

            {/* Simulated Profile Avatar */}
            <div className="flex items-center gap-2">
              <div className="w-8 h-8 rounded-full border border-neutral-300 bg-neutral-800 flex items-center justify-center text-xs text-white font-bold overflow-hidden shadow-inner">
                HMI
              </div>
            </div>
          </div>
        </header>

        {/* WORKSPACE LAYOUT ACCORDING TO USER'S SELECTED TAB */}
        {activeTab === 'manufacturing' ? (
          <div 
            id="manufacturing_view_layout"
            className="flex-1 p-5 grid grid-cols-1 xl:grid-cols-3 gap-6 h-[calc(100vh-8rem)] overflow-y-auto bg-neutral-100 select-none pb-12"
          >
            {/* COLUMN 1: INPUT IMAGE + FILE CONTROL */}
            <div className="flex flex-col gap-6">
              {/* Group Input Image */}
              <div 
                id="group_input"
                className="bg-white border-2 border-neutral-300 rounded px-4 pt-5 pb-4 shadow-xs relative flex flex-col justify-between"
              >
                <span className="absolute -top-3 left-4 bg-neutral-100 px-2 text-xs font-mono font-bold text-neutral-800 border-2 border-neutral-300 rounded">
                  Input Image
                </span>
                
                <div className="mt-2 flex flex-col gap-3">
                  <div 
                    id="input_window"
                    className="relative w-full aspect-square max-h-[300px] bg-neutral-950 border-2 border-neutral-800 rounded flex flex-col justify-between p-3 overflow-hidden shadow-inner font-mono text-[10px] text-neutral-400"
                  >
                    <div className="flex justify-between items-center text-neutral-500 border-b border-neutral-900 pb-1 text-[8px]">
                      <span>CHASSIS FILE SLICER v2.4</span>
                      <span className="text-blue-500 animate-pulse font-bold">SOURCE_VECTOR</span>
                    </div>
                    <div className="flex-1 flex items-center justify-center p-2 animate-none">
                      <svg viewBox="0 0 220 230" className="w-full h-full max-h-[220px] drop-shadow-[0_0_10px_rgba(59,130,246,0.3)] select-none">
                        {activeModel.drawPaths(currentLayer, threshold)}
                      </svg>
                    </div>
                    <div className="text-[8px] text-neutral-500 flex justify-between border-t border-neutral-900 pt-1">
                      <span>SCALE: 100% | THRESHOLD: {threshold}</span>
                      <span>READY 1-BIT</span>
                    </div>
                  </div>
                </div>
              </div>

              {/* Group File Control */}
              <div 
                id="group_file"
                className="bg-white border-2 border-neutral-300 rounded px-4 pt-5 pb-4 shadow-xs relative flex flex-col justify-between"
              >
                <span className="absolute -top-3 left-4 bg-neutral-100 px-2 text-xs font-mono font-bold text-neutral-800 border-2 border-neutral-300 rounded">
                  File control
                </span>

                <div className="mt-2 flex flex-col gap-4">
                  {/* Row 0 of File group: Open, Convert, Show Info buttons */}
                  <div className="grid grid-cols-3 gap-2">
                    <div className="relative">
                      <button 
                        id="file_open_button"
                        className="w-full py-2 text-xs font-mono font-bold rounded border-2 border-neutral-300 bg-neutral-50 hover:bg-neutral-150 text-neutral-800 flex items-center justify-center gap-1 cursor-pointer"
                      >
                        <Upload className="w-3.5 h-3.5" /> OPEN FILE
                      </button>
                      <select
                        id="combo_select_cad_job"
                        value={selectedModelIdx}
                        onChange={(e) => {
                          const idx = Number(e.target.value);
                          setSelectedModelIdx(idx);
                          setCurrentLayer(1);
                          addLog(`[FILE] Loaded print design file: ${cadModels[idx].filename}`);
                        }}
                        className="absolute inset-0 opacity-0 cursor-pointer"
                      >
                        {cadModels.map((m, i) => (
                          <option key={i} value={i}>{m.name}</option>
                        ))}
                      </select>
                    </div>

                    <button 
                      id="file_convert_button"
                      onClick={() => {
                        setThreshold(128);
                        addLog("[FILE] Triggered image raster thresh alignment. Reset to 128.");
                      }}
                      className="py-2 text-xs font-mono font-bold rounded border-2 border-neutral-300 bg-neutral-50 hover:bg-neutral-150 text-neutral-800 flex items-center justify-center gap-1 cursor-pointer"
                    >
                      <Undo className="w-3.5 h-3.5" /> CONVERT
                    </button>

                    <button 
                      id="file_show_full_button"
                      onClick={() => {
                        alert(`Model properties:\nName: ${activeModel.name}\nFilename: ${activeModel.filename}\nDPI Resolution: ${activeModel.dpi}\nLayers: ${activeModel.layers}`);
                        addLog(`[FILE] Inquired model stats: ${activeModel.name}`);
                      }}
                      className="py-2 text-[10px] font-mono font-bold rounded border-2 border-neutral-300 bg-neutral-50 hover:bg-neutral-150 text-neutral-700 truncate cursor-pointer"
                    >
                      SHOW INFO
                    </button>
                  </div>

                  {/* Row 1: threshold_slider */}
                  <div className="flex flex-col gap-1">
                    <div className="flex justify-between text-[11px] font-mono text-neutral-500 uppercase tracking-widest pl-1">
                      <span>Threshold Limit</span>
                      <strong className="text-blue-600">{threshold} / 255</strong>
                    </div>
                    <input 
                      id="threshold_slider"
                      type="range" 
                      min="1" 
                      max="255" 
                      value={threshold} 
                      onChange={(e) => setThreshold(Number(e.target.value))}
                      className="w-full accent-blue-600 h-1.5 bg-neutral-200 rounded-lg cursor-pointer"
                    />
                  </div>

                  {/* Row 2: threshold_slider_value (QLabel) */}
                  <span 
                    id="threshold_slider_value" 
                    className="text-xs font-mono font-bold text-neutral-600 bg-neutral-50 border border-neutral-200 px-2.5 py-1.5 rounded text-center block"
                  >
                    Active threshold filter offset: L={threshold} index units
                  </span>

                  {/* Row 3: file_dimensions_title + file_dimensions */}
                  <div className="grid grid-cols-3 gap-2 items-center">
                    <span 
                      id="file_dimensions_title"
                      className="text-xs font-mono text-neutral-500 font-bold uppercase pl-1"
                    >
                      DIMENSIONS
                    </span>
                    <input 
                      id="file_dimensions"
                      type="text"
                      value={fileDimensionsInput}
                      onChange={(e) => setFileDimensionsInput(e.target.value)}
                      className="col-span-2 py-1.5 px-3 text-xs font-mono text-neutral-800 bg-neutral-50 border-2 border-neutral-300 rounded focus:border-blue-500 outline-hidden uppercase"
                    />
                  </div>
                </div>
              </div>
            </div>

            {/* COLUMN 2: OUTPUT IMAGE + PRINT CONTROL */}
            <div className="flex flex-col gap-6">
              {/* Group Output Image */}
              <div 
                id="group_output"
                className="bg-white border-2 border-neutral-300 rounded px-4 pt-5 pb-4 shadow-xs relative flex flex-col justify-between"
              >
                <span className="absolute -top-3 left-4 bg-neutral-100 px-2 text-xs font-mono font-bold text-neutral-800 border-2 border-neutral-300 rounded">
                  Output Image
                </span>

                <div className="mt-2 flex flex-col gap-3">
                  <div 
                    id="output_window"
                    className="relative w-full aspect-square max-h-[300px] bg-neutral-950 border-2 border-neutral-800 rounded overflow-hidden shadow-inner font-mono text-[10px] text-white"
                  >
                    {/* Concentric grid lines of powder bed */}
                    <div className="absolute inset-0 bg-neutral-900 flex items-center justify-center">
                      <div className="w-[85%] h-[85%] border-2 border-dashed border-blue-500/80 rounded relative bg-neutral-950/85 flex items-center justify-center">
                        {/* Alignment circles */}
                        <div className="absolute inset-4 border border-neutral-800 rounded-full pointer-events-none"></div>
                        <div className="absolute inset-12 border border-neutral-800 rounded-full pointer-events-none"></div>
                        {/* Core center bounding */}
                        <div className="w-1/3 h-1/3 border border-neutral-800 bg-neutral-900/90 rounded flex flex-col items-center justify-center p-1 text-[8px] text-neutral-400 shadow-md">
                          <span>PRINTBED_A</span>
                          <span className="text-blue-400 font-bold mt-1 text-[9px]">{currentPercent}% Slice</span>
                        </div>
                        {/* Crosshair coordinate tracking */}
                        <div 
                          className="absolute w-6 h-6 flex items-center justify-center pointer-events-none transition-all duration-300"
                          style={{
                            left: `${Math.max(10, Math.min(90, (coords.x / 220) * 100))}%`,
                            top: `${Math.max(10, Math.min(90, (coords.y / 200) * 100))}%`
                          }}
                        >
                          <div className="w-2 h-2 rounded-full bg-green-500 animate-ping absolute"></div>
                          <div className="w-1.5 h-1.5 rounded-full bg-green-500"></div>
                          <div className="absolute w-4 h-px bg-green-500/60"></div>
                          <div className="absolute h-4 w-px bg-green-500/60"></div>
                        </div>
                      </div>
                    </div>
                    
                    {/* Moving Recoater Spreader */}
                    <div 
                      className="absolute top-0 bottom-0 w-6 bg-neutral-800 border-l border-r border-neutral-600 shadow-[2px_0_8px_rgba(0,0,0,0.5)] flex flex-col items-center justify-between py-1 transition-all duration-100 ease-linear z-10"
                      style={{ left: `${recoaterPosition}%` }}
                    >
                      <div className="text-[7px] text-neutral-400 [writing-mode:vertical-lr] tracking-widest font-bold font-mono">RECOATER</div>
                      <div className="w-1.5 h-1.5 rounded-full bg-blue-500 animate-pulse"></div>
                    </div>

                    {/* Spraying head gantry */}
                    {isSprayingCheck && (
                      <div 
                        className="absolute left-0 right-0 h-8 bg-neutral-950/90 border-t border-b border-blue-500 flex items-center justify-center z-15 transition-all duration-75"
                        style={{ top: `${carriagePosition}%` }}
                      >
                        <div className="w-full text-center text-blue-400 text-[8px] font-mono tracking-widest animate-pulse font-bold">
                          HP45 JETTING ACTIVE
                        </div>
                      </div>
                    )}

                    {/* HUD Indicators overlay */}
                    <div className="absolute bottom-2 left-2 bg-neutral-900/85 px-1.5 py-0.5 rounded border border-neutral-800 text-[8px] text-neutral-400">
                      Z1:{coords.feed.toFixed(3)} mm | Z2:{coords.build.toFixed(3)} mm
                    </div>
                  </div>
                </div>
              </div>

              {/* Group Print Control */}
              <div 
                id="group_print"
                className="bg-white border-2 border-neutral-300 rounded px-4 pt-5 pb-4 shadow-xs relative flex flex-col justify-between"
              >
                <span className="absolute -top-3 left-4 bg-neutral-100 px-2 text-xs font-mono font-bold text-neutral-800 border-2 border-neutral-300 rounded">
                  Print Control
                </span>

                <div className="mt-2 flex flex-col gap-3">
                  {/* Row 0: layer_slider + layer_slider_value */}
                  <div className="flex flex-col gap-1.5">
                    <div className="flex justify-between items-center text-xs font-mono px-1">
                      <span className="text-neutral-500 font-bold uppercase">Index Slider</span>
                      <strong id="layer_slider_value" className="text-neutral-900 bg-neutral-200 px-1.5 py-0.5 rounded select-text">
                        Layer: {currentLayer} / {activeModel.layers}
                      </strong>
                    </div>
                    <input 
                      id="layer_slider"
                      type="range"
                      min="1"
                      max={activeModel.layers}
                      value={currentLayer}
                      onChange={(e) => {
                        const val = Number(e.target.value);
                        setCurrentLayer(val);
                        addLog(`[MANUAL SLICE] Moved slice layers selector index to layer ${val}.`);
                      }}
                      className="w-full accent-neutral-800 h-1.5 bg-neutral-200 rounded-lg cursor-pointer"
                    />
                  </div>

                  {/* Row 1-2: ComboBox dropdown selectors */}
                  <div className="grid grid-cols-3 gap-2 mt-1">
                    <div className="flex flex-col gap-1">
                      <span id="dpi_title" className="text-[10px] font-mono font-bold text-neutral-400 uppercase tracking-tight">Data DPI</span>
                      <select 
                        id="dpi_combo"
                        value={selectedDpi}
                        onChange={(e) => {
                          setSelectedDpi(e.target.value);
                          addLog(`[PRINT] Registering head resolution index multiplier: ${e.target.value}`);
                        }}
                        className="py-1 px-1.5 text-[11px] font-mono font-bold bg-neutral-50 rounded border-2 border-neutral-300 text-neutral-700 cursor-pointer focus:border-neutral-500"
                      >
                        <option value="600 DPI">600 DPI</option>
                        <option value="300 DPI">300 DPI</option>
                        <option value="150 DPI">150 DPI</option>
                        <option value="75 DPI">75 DPI</option>
                      </select>
                    </div>

                    <div className="flex flex-col gap-1">
                      <span id="sweeps_title" className="text-[10px] font-mono font-bold text-neutral-400 uppercase tracking-tight">Sweeps per area</span>
                      <select 
                        id="sweep_combo"
                        value={selectedSweep}
                        onChange={(e) => {
                          setSelectedSweep(e.target.value);
                          addLog(`[PRINT] Swaps print passes density cycles modified to: ${e.target.value}`);
                        }}
                        className="py-1 px-1.5 text-[11px] font-mono font-bold bg-neutral-50 rounded border-2 border-neutral-300 text-neutral-700 cursor-pointer focus:border-neutral-500"
                      >
                        <option value="1 Sweep">1 Sweep</option>
                        <option value="2 Sweeps">2 Sweeps</option>
                        <option value="3 Sweeps">3 Sweeps</option>
                      </select>
                    </div>

                    <div className="flex flex-col gap-1">
                      <span id="mode_title" className="text-[10px] font-mono font-bold text-neutral-400 uppercase tracking-tight">Printing mode</span>
                      <select 
                        id="mode_combo"
                        value={selectedMode}
                        onChange={(e) => {
                          setSelectedMode(e.target.value);
                          addLog(`[PRINT] Modified jetting raster sequence strategy to: ${e.target.value}`);
                        }}
                        className="py-1 px-1.5 text-[11px] font-mono font-bold bg-neutral-50 rounded border-2 border-neutral-300 text-neutral-700 cursor-pointer focus:border-neutral-500"
                      >
                        <option value="3D Printing">3D Printing</option>
                        <option value="2D Printing">2D Printing</option>
                        <option value="Calibration">Calibration</option>
                      </select>
                    </div>
                  </div>

                  {/* Row 3: Start from layer Spinbox */}
                  <div className="grid grid-cols-3 gap-2 items-center mt-1">
                    <span id="start_layer_label" className="text-[11px] font-mono font-bold text-neutral-500 uppercase tracking-tighter">Start layer:</span>
                    <input 
                      id="start_layer_spinbox"
                      type="number"
                      min="1"
                      max={activeModel.layers}
                      value={startLayerSpinbox}
                      onChange={(e) => {
                        const val = Math.max(1, Math.min(activeModel.layers, Number(e.target.value)));
                        setStartLayerSpinbox(val);
                        addLog(`[PRINT] Start point boundary index shifted to layer: ${val}`);
                      }}
                      className="col-span-2 py-1 px-2.5 text-xs font-mono font-bold text-neutral-800 bg-neutral-50 border-2 border-neutral-300 rounded focus:border-neutral-500 focus:outline-hidden"
                    />
                  </div>

                  {/* Row 4: Primary physical triggers (Print, Pause, Abort) */}
                  <div className="grid grid-cols-3 gap-2 mt-2">
                    <button 
                      id="file_print_button"
                      onClick={handlePrint}
                      disabled={isPrinting}
                      className="py-2.5 text-xs font-mono font-bold rounded-sm border-2 border-blue-800 bg-blue-600 hover:bg-blue-700 text-white disabled:opacity-40 transition-colors uppercase cursor-pointer flex items-center justify-center gap-1 shadow-xs animate-none"
                    >
                      <Play className="w-3.5 h-3.5 fill-white" /> PRINT
                    </button>

                    <button 
                      id="pause_button"
                      onClick={handlePause}
                      disabled={!isPrinting}
                      className={`py-2.5 text-xs font-mono font-bold rounded-sm border-2 transition-colors uppercase cursor-pointer flex items-center justify-center gap-1 shadow-xs ${
                        isPaused 
                          ? 'bg-amber-500 border-amber-700 text-white animate-pulse' 
                          : 'bg-neutral-100 border-neutral-300 hover:bg-neutral-200 text-neutral-800 disabled:opacity-40'
                      }`}
                    >
                      <Pause className="w-3.5 h-3.5" /> PAUSE
                    </button>

                    <button 
                      id="abort_button"
                      onClick={handleAbort}
                      className="py-2.5 text-xs font-mono font-bold rounded-sm border-2 border-red-800 bg-red-650 hover:bg-red-700 text-white transition-colors uppercase cursor-pointer flex items-center justify-center gap-1 shadow-xs"
                    >
                      <Square className="w-3.5 h-3.5 fill-white" /> ABORT
                    </button>
                  </div>
                </div>
              </div>
            </div>

            {/* COLUMN 3: RIGHT PANEL (JOG MOTION + INKJET) */}
            <div 
              id="hardware_manual_override_column" 
              className="flex flex-col gap-6"
            >
              {/* Group A: Motion Connection */}
              <div 
                id="group_motion"
                className="bg-white border-2 border-neutral-300 rounded px-4 pt-5 pb-4 shadow-xs relative flex flex-col justify-between animate-none"
              >
                <span className="absolute -top-3 left-4 bg-neutral-100 px-2 text-xs font-mono font-bold text-neutral-800 border-2 border-neutral-300 rounded">
                  Motion Connection
                </span>

                <div className="mt-2 flex flex-col gap-3">
                  <div className="grid grid-cols-2 gap-2 items-center">
                    <span id="motion_com_lbl" className="text-xs font-mono text-neutral-500 font-bold uppercase pl-1 animate-none">Com Port</span>
                    <input 
                      id="motion_com_port"
                      type="text"
                      value={motionPort}
                      onChange={(e) => setMotionPort(e.target.value)}
                      className="py-1 px-2.5 text-xs font-mono font-bold text-neutral-800 bg-neutral-50 border-2 border-neutral-300 rounded focus:border-neutral-500 focus:outline-hidden"
                    />
                  </div>

                  <div className="grid grid-cols-2 gap-2 items-center">
                    <span id="motion_baud_lbl" className="text-xs font-mono text-neutral-500 font-bold uppercase pl-1 animate-none">Baudrate</span>
                    <select 
                      id="motion_baudrate"
                      defaultValue="115200"
                      className="py-1 px-2.5 text-xs font-mono font-bold text-neutral-700 bg-neutral-50 border-2 border-neutral-300 rounded focus:border-neutral-500 focus:outline-hidden"
                    >
                      <option value="115200">115200</option>
                      <option value="250000">250000</option>
                      <option value="57600">57600</option>
                      <option value="9600">9600</option>
                    </select>
                  </div>

                  <div className="flex gap-2 items-center justify-between mt-1 pt-1 border-t border-neutral-100">
                    <button 
                      id="motion_connect_button"
                      onClick={() => {
                        setIsMotionConnected(!isMotionConnected);
                        addLog(`[MOTION] ${!isMotionConnected ? 'Connected to GRBL controller on ' + motionPort : 'Disconnected GRBL connection'}`);
                      }}
                      className={`flex-1 py-1.5 text-xs font-mono font-bold rounded-sm border-2 transition-all cursor-pointer ${
                        isMotionConnected 
                          ? "bg-green-600 border-green-700 text-white hover:bg-green-750" 
                          : "bg-neutral-50 border-neutral-300 hover:bg-neutral-100 text-neutral-800"
                      }`}
                    >
                      {isMotionConnected ? "DISCONNECT" : "CONNECT"}
                    </button>
                    <span 
                      id="motion_status_lbl"
                      className={`text-[10px] font-mono font-bold px-2 py-1 rounded-sm border ${
                        isMotionConnected 
                          ? "bg-green-50 text-green-700 border-green-200" 
                          : "bg-red-50 text-red-700 border-red-200"
                      }`}
                    >
                      {isMotionConnected ? "CONNECTED" : "OFFLINE"}
                    </span>
                  </div>
                </div>
              </div>

              {/* Group B: Inkjet Connection */}
              <div 
                id="group_inkjet"
                className="bg-white border-2 border-neutral-300 rounded px-4 pt-5 pb-4 shadow-xs relative flex flex-col justify-between animate-none"
              >
                <span className="absolute -top-3 left-4 bg-neutral-100 px-2 text-xs font-mono font-bold text-neutral-800 border-2 border-neutral-300 rounded">
                  Inkjet Connection
                </span>

                <div className="mt-2 flex flex-col gap-3">
                  <div className="grid grid-cols-2 gap-2 items-center">
                    <span id="inkjet_com_lbl" className="text-xs font-mono text-neutral-500 font-bold uppercase pl-1 animate-none">Com Port</span>
                    <input 
                      id="inkjet_com_port"
                      type="text"
                      value={inkjetPort}
                      onChange={(e) => setInkjetPort(e.target.value)}
                      className="py-1 px-2.5 text-xs font-mono font-bold text-neutral-800 bg-neutral-50 border-2 border-neutral-300 rounded focus:border-neutral-500 focus:outline-hidden"
                    />
                  </div>

                  <div className="flex gap-2 items-center justify-between mt-1 pt-1 border-t border-neutral-100">
                    <button 
                      id="inkjet_connect_button"
                      onClick={() => {
                        setIsInkjetConnected(!isInkjetConnected);
                        addLog(`[INKJET] ${!isInkjetConnected ? 'Opened HP45 inkjet channel on ' + inkjetPort : 'Closed HP45 channel line'}`);
                      }}
                      className={`flex-1 py-1.5 text-xs font-mono font-bold rounded-sm border-2 transition-all cursor-pointer ${
                        isInkjetConnected 
                          ? "bg-green-600 border-green-700 text-white hover:bg-green-755" 
                          : "bg-neutral-50 border-neutral-300 hover:bg-neutral-100 text-neutral-800"
                      }`}
                    >
                      {isInkjetConnected ? "DISCONNECT" : "CONNECT"}
                    </button>
                    <span 
                      id="inkjet_status_lbl"
                      className={`text-[10px] font-mono font-bold px-2 py-1 rounded-sm border ${
                        isInkjetConnected 
                          ? "bg-green-50 text-green-700 border-green-200" 
                          : "bg-red-50 text-red-700 border-red-200"
                      }`}
                    >
                      {isInkjetConnected ? "CONNECTED" : "OFFLINE"}
                    </span>
                  </div>
                </div>
              </div>

              {/* Group C: Motion Functions */}
              <div 
                id="group_motion_functions"
                className="bg-white border-2 border-neutral-300 rounded px-4 pt-5 pb-4 shadow-xs relative flex flex-col justify-between animate-none"
              >
                <span className="absolute -top-3 left-4 bg-neutral-100 px-2 text-xs font-mono font-bold text-neutral-800 border-2 border-neutral-300 rounded">
                  Motion functions
                </span>

                <div className="mt-2 flex flex-col gap-4">
                  {/* Position Readouts */}
                  <div className="grid grid-cols-2 gap-2 bg-neutral-50 p-2.5 border border-neutral-200 rounded text-xs font-mono">
                    <div className="flex flex-col gap-1.5">
                      <div className="flex justify-between border-b border-neutral-200 pb-1">
                        <span id="motion_x_pos_title" className="text-neutral-500 font-bold">X pos</span>
                        <strong id="motion_x_pos" className="text-neutral-800 font-bold">{coords.x.toFixed(3)}</strong>
                      </div>
                      <div className="flex justify-between border-b border-neutral-200 pb-1">
                        <span id="motion_y_pos_title" className="text-neutral-500 font-bold">Y pos</span>
                        <strong id="motion_y_pos" className="text-neutral-800 font-bold">{coords.y.toFixed(3)}</strong>
                      </div>
                      <div className="flex justify-between">
                        <span id="motion_r_pos_title" className="text-neutral-500 font-bold">Recoater</span>
                        <strong id="motion_r_pos" className="text-neutral-800 font-bold">{recoaterPosition.toFixed(1)}%</strong>
                      </div>
                    </div>

                    <div className="flex flex-col gap-1.5 pl-2 border-l border-neutral-200">
                      <div className="flex justify-between border-b border-neutral-200 pb-1">
                        <span id="motion_b_pos_title" className="text-neutral-500 font-bold">Build Z2</span>
                        <strong id="motion_b_pos" className="text-neutral-800 font-bold">{coords.build.toFixed(3)} mm</strong>
                      </div>
                      <div className="flex justify-between border-b border-neutral-200 pb-1">
                        <span id="motion_f_pos_title" className="text-neutral-500 font-bold">Feed Z1</span>
                        <strong id="motion_f_pos" className="text-neutral-800 font-bold">{coords.feed.toFixed(3)} mm</strong>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-neutral-400 font-bold font-semibold uppercase">Status</span>
                        <span className="text-blue-600 font-bold font-mono">G_IDLE</span>
                      </div>
                    </div>
                  </div>

                  {/* Jog Wheel: Direction and Inputs */}
                  <div className="flex flex-col gap-3">
                    {/* XY Jog buttons */}
                    <div className="flex flex-col gap-1">
                      <span className="text-[10px] font-mono font-bold text-neutral-400 uppercase tracking-tighter text-left">Gantry XY Step size (mm)</span>
                      <div className="flex gap-2">
                        <input 
                          id="motion_step"
                          type="number"
                          step="0.1"
                          defaultValue="5.0"
                          className="w-20 py-1.5 px-2 text-center text-xs font-mono font-bold text-neutral-800 bg-neutral-50 border-2 border-neutral-300 rounded focus:border-neutral-500 focus:outline-hidden"
                        />
                        <div className="flex-1 grid grid-cols-4 gap-1">
                          <button 
                            id="btn_jog_left"
                            onClick={() => handleJog('X', '-')}
                            className="py-1 rounded border-2 border-neutral-300 bg-neutral-50 hover:bg-neutral-100 font-mono text-xs font-bold text-neutral-800 cursor-pointer"
                          >
                            X-
                          </button>
                          <button 
                            id="btn_jog_right"
                            onClick={() => handleJog('X', '+')}
                            className="py-1 rounded border-2 border-neutral-300 bg-neutral-50 hover:bg-neutral-100 font-mono text-xs font-bold text-neutral-800 cursor-pointer"
                          >
                            X+
                          </button>
                          <button 
                            id="btn_jog_up"
                            onClick={() => handleJog('Y', '+')}
                            className="py-1 rounded border-2 border-neutral-300 bg-neutral-50 hover:bg-neutral-100 font-mono text-xs font-bold text-neutral-800 cursor-pointer"
                          >
                            Y+
                          </button>
                          <button 
                            id="btn_jog_down"
                            onClick={() => handleJog('Y', '-')}
                            className="py-1 rounded border-2 border-neutral-300 bg-neutral-50 hover:bg-neutral-100 font-mono text-xs font-bold text-neutral-800 cursor-pointer"
                          >
                            Y-
                          </button>
                        </div>
                      </div>
                    </div>

                    {/* Build Piston (Z2) */}
                    <div className="flex flex-col gap-1">
                      <span className="text-[10px] font-mono font-bold text-neutral-400 uppercase tracking-tighter text-left">Build Piston (Z2) Step (mm)</span>
                      <div className="flex gap-2">
                        <input 
                          id="build_piston_step"
                          type="number"
                          step="0.05"
                          defaultValue="0.10"
                          className="w-20 py-1.5 px-2 text-center text-xs font-mono font-bold text-neutral-800 bg-neutral-50 border-2 border-neutral-300 rounded focus:border-neutral-500 focus:outline-hidden"
                        />
                        <div className="flex-1 grid grid-cols-2 gap-1">
                          <button 
                            id="btn_build_piston_up"
                            onClick={() => handlePistonAdjust('build', 'up')}
                            className="py-1 rounded border-2 border-neutral-300 bg-neutral-50 hover:bg-neutral-100 font-mono text-xs font-bold text-neutral-700 cursor-pointer"
                          >
                            UP [Z2+]
                          </button>
                          <button 
                            id="btn_build_piston_down"
                            onClick={() => handlePistonAdjust('build', 'dn')}
                            className="py-1 rounded border-2 border-neutral-300 bg-neutral-50 hover:bg-neutral-100 font-mono text-xs font-bold text-neutral-700 cursor-pointer"
                          >
                            DN [Z2-]
                          </button>
                        </div>
                      </div>
                    </div>

                    {/* Feed Piston (Z1) */}
                    <div className="flex flex-col gap-1">
                      <span className="text-[10px] font-mono font-bold text-neutral-400 uppercase tracking-tighter text-left">Feed Piston (Z1) Step (mm)</span>
                      <div className="flex gap-2">
                        <input 
                          id="feed_piston_step"
                          type="number"
                          step="0.05"
                          defaultValue="0.12"
                          className="w-20 py-1.5 px-2 text-center text-xs font-mono font-bold text-neutral-800 bg-neutral-50 border-2 border-neutral-300 rounded focus:border-neutral-500 focus:outline-hidden"
                        />
                        <div className="flex-1 grid grid-cols-2 gap-1">
                          <button 
                            id="btn_feed_piston_up"
                            onClick={() => handlePistonAdjust('feed', 'up')}
                            className="py-1 rounded border-2 border-neutral-300 bg-neutral-50 hover:bg-neutral-100 font-mono text-xs font-bold text-neutral-700 cursor-pointer"
                          >
                            UP [Z1+]
                          </button>
                          <button 
                            id="btn_feed_piston_down"
                            onClick={() => handlePistonAdjust('feed', 'dn')}
                            className="py-1 rounded border-2 border-neutral-300 bg-neutral-50 hover:bg-neutral-100 font-mono text-xs font-bold text-neutral-700 cursor-pointer"
                          >
                            DN [Z1-]
                          </button>
                        </div>
                      </div>
                    </div>

                    {/* Home Trigger button */}
                    <button 
                      id="motion_home_button"
                      onClick={() => handleUtilityAction('Homing')}
                      className="w-full py-2 mt-1 text-xs font-mono font-bold uppercase rounded border-2 border-neutral-300 bg-neutral-50 hover:bg-neutral-100 text-neutral-800 cursor-pointer animate-none"
                    >
                      HOME GANTRY AXIS (G28)
                    </button>
                  </div>
                </div>
              </div>

              {/* Group D: Inkjet Functions */}
              <div 
                id="group_inkjet_functions"
                className="bg-white border-2 border-neutral-300 rounded px-4 pt-5 pb-4 shadow-xs relative flex flex-col justify-between animate-none"
              >
                <span className="absolute -top-3 left-4 bg-neutral-100 px-2 text-xs font-mono font-bold text-neutral-800 border-2 border-neutral-300 rounded">
                  Inkjet Functions
                </span>

                <div className="mt-2 flex flex-col gap-4">
                  <div className="grid grid-cols-2 gap-3 text-xs font-mono">
                    <div className="flex flex-col gap-1">
                      <span id="voltage_lbl" className="text-neutral-400 font-semibold uppercase">Nozzle Voltage</span>
                      <input 
                        id="voltage_val"
                        type="text"
                        defaultValue="12.5 V"
                        className="py-1 px-2 text-xs font-mono font-bold text-neutral-800 bg-neutral-50 border-2 border-neutral-300 rounded focus:border-neutral-500 focus:outline-hidden"
                      />
                    </div>
                    
                    <div className="flex flex-col gap-1">
                      <span id="pulse_width_lbl" className="text-neutral-400 font-semibold uppercase">Pulse Width</span>
                      <input 
                        id="pulse_val"
                        type="text"
                        defaultValue="1.8 µs"
                        className="py-1 px-2 text-xs font-mono font-bold text-neutral-800 bg-neutral-50 border-2 border-neutral-300 rounded focus:border-neutral-500 focus:outline-hidden"
                      />
                    </div>
                  </div>

                  <div className="grid grid-cols-2 gap-3 text-xs font-mono items-end">
                    <div className="flex flex-col gap-1">
                      <span id="temp_lbl" className="text-neutral-400 font-semibold uppercase">Temperature Limit</span>
                      <input 
                        id="temperature_val"
                        type="text"
                        defaultValue="45 °C"
                        className="py-1 px-2 text-xs font-mono font-bold text-neutral-800 bg-neutral-50 border-2 border-neutral-300 rounded focus:border-neutral-500 focus:outline-hidden"
                      />
                    </div>
                    <button 
                      id="btn_set_temp"
                      onClick={() => {
                        addLog("[INKJET] Commited custom ceramic thermal sensor ceiling target parameters.");
                      }}
                      className="py-1 px-2 text-[10px] uppercase font-bold rounded border-2 bg-neutral-50 hover:bg-neutral-100 border-neutral-300 font-mono text-neutral-800 cursor-pointer h-[32px] flex items-center justify-center font-bold"
                    >
                      SET TEMP
                    </button>
                  </div>

                  <div className="grid grid-cols-2 gap-3 text-xs font-mono">
                    <div className="flex flex-col gap-1">
                      <span id="rescale_factor_lbl" className="text-neutral-400 font-semibold uppercase">Rescale Factor</span>
                      <input 
                        id="rescale_val"
                        type="text"
                        defaultValue="1.000"
                        className="py-1 px-2 text-xs font-mono font-bold text-neutral-800 bg-neutral-50 border-2 border-neutral-300 rounded focus:border-neutral-500 focus:outline-hidden"
                      />
                    </div>

                    <div className="flex flex-col gap-1">
                      <span id="recoater_speed_lbl" className="text-neutral-400 font-semibold uppercase">Recoater Speed</span>
                      <input 
                        id="recoater_speed"
                        type="text"
                        defaultValue="40 mm/s"
                        className="py-1 px-2 text-xs font-mono font-bold text-neutral-800 bg-neutral-50 border-2 border-neutral-300 rounded focus:border-neutral-500 focus:outline-hidden"
                      />
                    </div>
                  </div>

                  <div className="grid grid-cols-2 gap-3 text-xs font-mono">
                    <div className="flex flex-col gap-1">
                      <span id="recoater_wait_lbl" className="text-neutral-400 font-semibold uppercase">Recoater Wait</span>
                      <input 
                        id="recoater_wait"
                        type="text"
                        defaultValue="1.50 s"
                        className="py-1 px-2 text-xs font-mono font-bold text-neutral-800 bg-neutral-50 border-2 border-neutral-300 rounded focus:border-neutral-500 focus:outline-hidden"
                      />
                    </div>
                  </div>

                  {/* Primary head triggers */}
                  <div className="grid grid-cols-2 gap-2 border-t border-neutral-200 pt-3">
                    <button 
                      id="btn_set_density"
                      onClick={() => {
                        addLog("[INKJET] Registering print density matrix: threshold scaling aligning.");
                      }}
                      className="py-2 text-[11px] font-bold font-mono text-neutral-800 rounded border-2 border-neutral-300 bg-neutral-50 hover:bg-neutral-100 cursor-pointer font-bold"
                    >
                      SET DENSITY
                    </button>

                    <button 
                      id="btn_test_head"
                      onClick={() => handleUtilityAction('Test Head')}
                      className="py-2 text-[11px] font-bold font-mono text-neutral-800 rounded border-2 border-neutral-300 bg-neutral-50 hover:bg-neutral-100 cursor-pointer font-bold"
                    >
                      TEST HEAD
                    </button>

                    <button 
                      id="btn_head_clean"
                      onClick={() => {
                        addLog("[INKJET] High pressure solvent vacuum purge nozzle maintenance cycle.");
                      }}
                      className="py-2 text-[11px] font-bold font-mono text-neutral-800 rounded border-2 border-neutral-300 bg-neutral-50 hover:bg-neutral-100 cursor-pointer font-bold"
                    >
                      HEAD CLEAN
                    </button>

                    <button 
                      id="btn_purge"
                      onClick={() => handleUtilityAction('Purge')}
                      className="py-2 text-[11px] font-bold font-mono text-neutral-800 rounded border-2 border-neutral-300 bg-neutral-50 hover:bg-neutral-100 cursor-pointer font-bold"
                    >
                      PURGE
                    </button>
                  </div>

                  {/* Nozzles chip toggle indicators (highly responsive!) */}
                  <div className="flex flex-col gap-2 pt-2 border-t border-neutral-200">
                    <div className="flex justify-between items-center text-[10px] font-mono">
                      <span className="text-neutral-400 font-semibold">COATED HP45 NOZZLE GRID</span>
                      <strong className="text-blue-600 font-mono">{activeNozzlesCount} / {totalNozzles} OK</strong>
                    </div>

                    <div className="grid grid-cols-10 gap-1">
                      {nozzleChips.map((isActive, index) => (
                        <button
                          key={index}
                          onClick={() => toggleNozzleChip(index)}
                          className={`h-3.5 border rounded-xs cursor-pointer transition-colors ${
                            isActive 
                              ? 'bg-blue-600 border-blue-400 hover:bg-blue-700' 
                              : 'bg-red-600 border-red-400 hover:bg-red-700'
                          }`}
                          title={`Nozzle row segment ${index + 1}: ${isActive ? 'Active and Healthy' : 'Clogged (Tap to clean)'}`}
                        />
                      ))}
                    </div>

                    <div className="flex justify-between text-[8px] font-mono text-neutral-400">
                      <span>CHIP_01</span>
                      <span className="text-blue-500 font-bold bg-blue-50 px-1.5 py-0.2 rounded-xs border border-blue-100">BLUE: OK</span>
                      <span className="text-red-500 font-bold bg-red-50 px-1.5 py-0.2 rounded-xs border border-red-100">RED: CLOGGED</span>
                      <span>CHIP_10</span>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        ) : activeTab === 'monitoring' ? (
          <div className="flex-1 p-6 h-[calc(100vh-8rem)] overflow-y-auto">
            {/* ADVANCED MONITORING LAYOUT */}
            <div className="bg-white rounded-lg border border-neutral-200 shadow p-6 flex flex-col gap-6">
              <h2 className="text-lg font-bold text-neutral-800 uppercase tracking-widest font-mono flex items-center gap-2">
                <Sliders className="w-5 h-5 text-primary-blue animate-pulse" />
                Live Telemetry Monitors
              </h2>

              <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                <div className="bg-neutral-50 p-4 rounded border border-neutral-200">
                  <h3 className="text-xs uppercase font-mono text-neutral-400 font-bold mb-2">Axes Coordinates (step-count mm)</h3>
                  <div className="flex flex-col gap-2 font-mono">
                    <div className="flex justify-between border-b pb-1">
                      <span>X - Axis:</span>
                      <span className="text-primary-blue font-bold">{coords.x}</span>
                    </div>
                    <div className="flex justify-between border-b pb-1">
                      <span>Y - Axis:</span>
                      <span className="text-primary-blue font-bold">{coords.y}</span>
                    </div>
                    <div className="flex justify-between border-b pb-1">
                      <span>Feed Piston Height (Z1):</span>
                      <span className="text-neutral-700 font-bold">{coords.feed} mm</span>
                    </div>
                    <div className="flex justify-between">
                      <span>Build Piston Height (Z2):</span>
                      <span className="text-red-600 font-bold">{coords.build} mm</span>
                    </div>
                  </div>
                </div>

                <div className="bg-neutral-50 p-4 rounded border border-neutral-200">
                  <h3 className="text-xs uppercase font-mono text-neutral-400 font-bold mb-2">Pressure & Temperatures</h3>
                  <div className="flex flex-col gap-2 font-mono">
                    <div className="flex justify-between border-b pb-1">
                      <span>Head Print Temp:</span>
                      <span className="text-neutral-800 font-bold">{headTemp}°C</span>
                    </div>
                    <div className="flex justify-between border-b pb-1">
                      <span>Vacuum Pump State:</span>
                      <span className="text-neutral-800 font-bold">{vacuum} kPa</span>
                    </div>
                    <div className="flex justify-between border-b pb-1">
                      <span>Environmental Temp:</span>
                      <span className="text-neutral-600 font-bold">24.5 °C</span>
                    </div>
                    <div className="flex justify-between">
                      <span>Relative Humidity:</span>
                      <span className="text-neutral-600 font-bold">42 % RH</span>
                    </div>
                  </div>
                </div>

                <div className="bg-neutral-50 p-4 rounded border border-neutral-200">
                  <h3 className="text-xs uppercase font-mono text-neutral-400 font-bold mb-2">Inkjet Fluid Controller</h3>
                  <div className="flex flex-col gap-2 font-mono">
                    <div className="flex justify-between border-b pb-1">
                      <span>HP45 Controller Status:</span>
                      <span className="text-green-600 font-bold">LINKED</span>
                    </div>
                    <div className="flex justify-between border-b pb-1">
                      <span>Active Serial Port:</span>
                      <span className="text-neutral-700 font-bold">{comPort}</span>
                    </div>
                    <div className="flex justify-between border-b pb-1">
                      <span>Nozzles Active:</span>
                      <span className="text-primary-blue font-bold">{activeNozzlesCount} / 300</span>
                    </div>
                    <div className="flex justify-between">
                      <span>Jetting Duty Cycle:</span>
                      <span className="text-neutral-600 font-bold">14.8 %</span>
                    </div>
                  </div>
                </div>
              </div>

              {/* Graphic Plot visual simulator */}
              <div className="w-full bg-neutral-900 rounded p-4 border border-neutral-800 flex flex-col h-64 justify-between">
                <span className="text-xs font-mono text-neutral-400 uppercase tracking-widest font-bold">Real-time Oscilloscope Line (Vacuum kPa Offset)</span>
                <div className="flex-1 flex items-end justify-between gap-1 py-4 overflow-hidden">
                  {Array.from({ length: 48 }).map((_, idx) => {
                    const h = Math.abs(Math.sin((Date.now() + idx * 100) / 400) * 80) + Math.random() * 20 + 5;
                    return (
                      <div 
                        key={idx} 
                        className="bg-primary-blue/80 rounded-t flex-1" 
                        style={{ height: `${Math.max(10, Math.min(100, h))}%` }}
                      ></div>
                    );
                  })}
                </div>
                <div className="flex justify-between font-mono text-[9px] text-neutral-500">
                  <span>SWEEP TIMER_0_MS</span>
                  <span>-4.2 kPa MIDLINE</span>
                  <span>TIME SEC_60_HIST</span>
                </div>
              </div>
            </div>
          </div>
        ) : activeTab === 'maintenance' ? (
          <div className="flex-1 p-6 h-[calc(100vh-8rem)] overflow-y-auto">
            <div className="bg-white rounded-lg border border-neutral-200 shadow p-6 flex flex-col gap-6">
              <h2 className="text-lg font-bold text-neutral-800 uppercase tracking-widest font-mono flex items-center gap-2">
                <Activity className="w-5 h-5 text-green-500 animate-spin" />
                Hardware Calibration & Maintenance
              </h2>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4 font-mono text-sm">
                <div className="border rounded p-4 bg-neutral-50">
                  <h3 className="font-bold border-b pb-2 mb-3">Inkjet Head Calibration Matrix</h3>
                  <p className="text-xs text-neutral-500 mb-4 leading-relaxed">
                    Execute physical sweep lines to measure printhead drops misalignment offset indexes. Make sure the alignment optic system is clean.
                  </p>
                  <div className="grid grid-cols-3 gap-2">
                    <button 
                      onClick={() => alert("Firing diagnostic line vectors.")}
                      className="py-2 rounded bg-neutral-800 text-white text-xs hover:bg-neutral-700"
                    >
                      Print Matrix Line
                    </button>
                    <button 
                      onClick={() => alert("Re-calculating nozzle delta offsets.")}
                      className="py-2 rounded bg-neutral-100 hover:bg-neutral-200 text-xs text-neutral-700 border"
                    >
                      Auto Calibrate
                    </button>
                    <button 
                      onClick={() => alert("Jetting system diagnostics complete: 0 faults.")}
                      className="py-2 rounded bg-neutral-100 hover:bg-neutral-200 text-xs text-neutral-700 border"
                    >
                      Nozzle Diagnostics
                    </button>
                  </div>
                </div>

                <div className="border rounded p-4 bg-neutral-50">
                  <h3 className="font-bold border-b pb-2 mb-3">Powder Bed levelling Adjustment</h3>
                  <p className="text-xs text-neutral-550 mb-4 leading-relaxed">
                    Set relative heights parameters between primary sand hopper feed table and building chamber platform.
                  </p>
                  <div className="grid grid-cols-2 gap-3 text-xs">
                    <div className="flex justify-between items-center border p-2 rounded bg-white">
                      <span>Feed Max Limit:</span>
                      <strong className="text-primary-blue">25.000 mm</strong>
                    </div>
                    <div className="flex justify-between items-center border p-2 rounded bg-white">
                      <span>Build Max Limit:</span>
                      <strong className="text-red-600">-60.000 mm</strong>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        ) : (
          <div className="flex-1 p-6 h-[calc(100vh-8rem)] overflow-y-auto">
            <div className="bg-white rounded-lg border border-neutral-200 shadow p-6 flex flex-col h-full gap-4">
              <div className="flex justify-between items-center border-b pb-2">
                <h2 className="text-lg font-bold text-neutral-800 uppercase tracking-widest font-mono flex items-center gap-2">
                  <Terminal className="w-5 h-5 text-neutral-800" />
                  GRBL Serial Terminal Output
                </h2>
                <button 
                  onClick={() => alert("Clear terminal buffer log.")}
                  className="px-3 py-1 bg-neutral-100 text-neutral-600 rounded hover:bg-neutral-200 text-xs font-mono"
                >
                  Clear Logs
                </button>
              </div>

              {/* Dynamic scroll log area */}
              <div className="flex-1 bg-neutral-950 rounded p-4 font-mono text-xs text-neutral-300 overflow-y-auto flex flex-col gap-1.5 border border-neutral-800 max-h-[30rem]">
                {logsList.map((log, index) => {
                  let colorClass = "text-neutral-300";
                  if (log.includes("[ERROR]")) colorClass = "text-red-500 font-semibold animate-pulse";
                  else if (log.includes("[WARNING]")) colorClass = "text-amber-400";
                  else if (log.includes("[SYSTEM]")) colorClass = "text-green-400 font-medium";
                  else if (log.includes("[GCODE]")) colorClass = "text-blue-400";
                  else if (log.includes("[ROLLER]")) colorClass = "text-purple-400";
                  return (
                    <p key={index} className={colorClass}>{log}</p>
                  );
                })}
              </div>
            </div>
          </div>
        )}

        {/* BOTTOM REAL-TIME METRICS STATUS FOOTER BAR */}
        <footer 
          id="hmi_realtime_metrics_footer"
          className="h-16 w-full bg-neutral-900 border-t border-neutral-800 flex items-center justify-between px-6 font-mono text-xs text-neutral-400 shrink-0 z-10 select-all"
        >
          {/* Coordinates section */}
          <div className="flex items-center gap-6 divide-x divide-neutral-800">
            <div id="footer_coord_x" className="flex gap-1.5 items-center">
              <span className="text-neutral-500 font-bold uppercase">X:</span>
              <span className="text-primary-blue font-bold text-sm tracking-wider select-text min-w-[70px]">
                {coords.x.toFixed(3)}
              </span>
            </div>
            
            <div id="footer_coord_y" className="pl-6 flex gap-1.5 items-center">
              <span className="text-neutral-500 font-bold uppercase">Y:</span>
              <span className="text-primary-blue font-bold text-sm tracking-wider select-text min-w-[70px]">
                {coords.y.toFixed(3)}
              </span>
            </div>

            <div id="footer_coord_feed" className="pl-6 flex gap-1.5 items-center">
              <span className="text-neutral-500 font-bold uppercase">Feed:</span>
              <span className="text-neutral-200 font-bold text-sm tracking-wider select-text min-w-[70px]">
                {coords.feed.toFixed(3)}
              </span>
            </div>

            <div id="footer_coord_build" className="pl-6 flex gap-1.5 items-center">
              <span className="text-neutral-500 font-bold uppercase">Build:</span>
              <span className="text-red-500 font-bold text-sm tracking-wider select-text min-w-[70px]">
                {coords.build.toFixed(3)}
              </span>
            </div>
          </div>

          {/* Machine state and metadata section */}
          <div className="flex items-center gap-6">
            <div className="flex items-center gap-2">
              <span className="text-neutral-550 select-none uppercase font-bold text-[10px]">Status:</span>
              <span 
                id="footer_status_badge"
                className={`px-3 py-1 rounded text-xs font-bold uppercase tracking-widest leading-none ${
                  !isEmergencyUnlocked 
                    ? 'bg-red-650 text-white animate-pulse' 
                    : isPrinting 
                      ? 'bg-blue-600 text-white animate-pulse' 
                      : 'bg-green-600 text-white'
                }`}
              >
                {!isEmergencyUnlocked ? 'SAFETY LOCKED' : isPrinting ? 'PRINTING' : 'READY'}
              </span>
            </div>

            <span className="h-4 w-px bg-neutral-800"></span>

            <p className="text-xs text-neutral-300">
              Active Job: <strong id="lbl_active_job_filename" className="text-white hover:underline cursor-help">{activeModel.filename}</strong>
            </p>

            <span className="h-4 w-px bg-neutral-800"></span>

            <p>
              Layer: <strong className="text-white font-mono">{currentLayer}/{activeModel.layers}</strong>
            </p>

            <span className="h-4 w-px bg-neutral-800"></span>

            <p className="flex items-center gap-1">
              Head: <strong className={`text-white transition-colors duration-300 ${headTemp > 44 ? 'text-amber-400' : ''}`}>{headTemp}°C</strong>
            </p>

            <span className="h-4 w-px bg-neutral-800"></span>

            <p>
              Vacuum: <strong className="text-white">{vacuum} kPa</strong>
            </p>

            <span className="h-4 w-px bg-neutral-800"></span>

            {/* Version indicator line */}
            <p className="text-neutral-500 select-none hover:text-white transition-all text-[11px]">
              INDUSTRIAL HMI SYSTEM V2.4.1
            </p>
          </div>
        </footer>
      </div>
    </div>
  );
}
