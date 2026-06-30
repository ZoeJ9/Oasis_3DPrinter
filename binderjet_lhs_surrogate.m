%% binderjet_lhs_surrogate.m
% Latin Hypercube DOE generation + Gaussian-process surrogate for
% binder-jet printing.
%
% Requires: Statistics and Machine Learning Toolbox (lhsdesign, fitrgp).
%           (No Global Optimization Toolbox needed - optimum is found by
%            dense sampling of the cheap surrogate.)
%
% Two stages:
%   Stage A  -> generate LHS design, write doe_plan.csv, run those on printer
%   Stage B  -> load measured responses, fit GP, validate, rank factors, optimize
%
% The ranges in factors{} are PLACEHOLDERS. Edit them to your real limits
% and units before generating a plan you intend to actually print.

clear; clc; rng(42);                 % reproducible

%% 0. Configuration -----------------------------------------------------
N_SAMPLES     = 30;                  % DOE runs. Rule of thumb: >= 8-10x #factors
RUN_DEMO      = true;                % true = fabricate Y to test the pipeline
RESPONSE_NAME = 'green_density';     % the thing you measure per print

%% 1. Factor definitions ------------------------------------------------
% Columns: name | min | max | type
%   type = 'cont' continuous | 'int' integer | numeric vector = discrete levels
factors = {
%   name               min     max    type
    'density',          50,    250,   'int'          % fire %, main saturation knob
    'dpi',             150,    600,   [150 300 600]  % hardware-allowed levels
    'layer_passes',      1,      4,   'int'          % passes per layer
    'print_speed',      20,    120,   'cont'         % mm/s  (set your units)
    'layer_thickness',  50,    200,   'cont'         % um, build-global
    'spread_speed',   1000,  10000,   'cont'         % recoater speed, default 6000
    'overfeed',        1.5,    3.0,   'cont'         % dispense ratio
};
names = factors(:,1);
lo    = cell2mat(factors(:,2));
hi    = cell2mat(factors(:,3));
types = factors(:,4);
nF    = numel(names);

%% 2. Latin Hypercube design -------------------------------------------
U = lhsdesign(N_SAMPLES, nF, 'criterion','maximin', 'iterations',200);
X = zeros(N_SAMPLES, nF);
for j = 1:nF
    x = lo(j) + U(:,j).*(hi(j)-lo(j));     % unit cube -> physical range
    X(:,j) = enforce_col(x, types{j});     % round ints / snap to levels
end

doe = array2table(X, 'VariableNames', names');
doe.S_est = saturation(doe);               % physics feature for design QC (see note)

writetable(doe, 'doe_plan.csv');
fprintf('Stage A: wrote %d-run DOE to doe_plan.csv\n', N_SAMPLES);
fprintf('  S_est coverage: %.3f to %.3f (target window ~0.6-0.8)\n', ...
        min(doe.S_est), max(doe.S_est));

%% 3. Load results & fit surrogate -------------------------------------
% After printing: add a measured-response column to the plan, save as
% doe_results.csv, then run the rest with RUN_DEMO = false.
if RUN_DEMO
    Y = demo_response(X);                   % synthetic ground truth (testing only)
else
    R = readtable('doe_results.csv');
    Y = R.(RESPONSE_NAME);
    X = R{:, names};                        % re-read X to keep row order aligned
end

gp = fitrgp(X, Y, ...
    'KernelFunction','ardsquaredexponential', ...   % per-factor length scales
    'Basis','constant', 'Standardize',true, ...
    'FitMethod','exact', 'PredictMethod','exact');

%% 4. Validate (cross-validation) --------------------------------------
k   = min(10, N_SAMPLES);                   % use 'Leaveout',true for tiny N
cv  = crossval(gp, 'KFold', k);
yhat = kfoldPredict(cv);
R2   = 1 - sum((Y-yhat).^2)/sum((Y-mean(Y)).^2);
RMSE = sqrt(mean((Y-yhat).^2));
fprintf('\nStage B: CV R^2 = %.3f   RMSE = %.3g\n', R2, RMSE);

figure; plot(Y, yhat, 'o'); hold on; plot(xlim, xlim, 'k--');
xlabel('measured'); ylabel('predicted (CV)');
title(sprintf('Surrogate parity  (R^2 = %.3f)', R2)); axis equal; grid on;

%% 5. Factor importance from ARD length scales -------------------------
% Short length scale -> response varies fast in that factor -> influential.
L = gp.KernelInformation.KernelParameters(1:nF);
importance = (hi - lo) ./ L;                % normalize by factor span
importance = importance / max(importance);
[~, ord] = sort(importance, 'descend');

figure; bar(importance(ord));
set(gca, 'XTick',1:nF, 'XTickLabel', names(ord), 'XTickLabelRotation', 40);
ylabel('relative sensitivity'); title('ARD-based factor importance'); grid on;

%% 6. Optimize over the surrogate --------------------------------------
% Maximize predicted response by densely sampling the cheap GP.
M  = 20000;
Uo = lhsdesign(M, nF);
Z  = lo' + Uo .* (hi' - lo');
for j = 1:nF, Z(:,j) = enforce_col(Z(:,j), types{j}); end
[ypred, ysd] = predict(gp, Z);
[ybest, ix]  = max(ypred);

fprintf('\nPredicted optimum: %s = %.4g  (GP sd %.3g)\n', ...
        RESPONSE_NAME, ybest, ysd(ix));
disp(array2table(Z(ix,:), 'VariableNames', names'));
fprintf(['NOTE: validate the optimum with a confirmation print - it can ' ...
         'sit\n      outside the sampled region where the GP extrapolates.\n']);

%% ===================== helper functions ============================= %%
function x = enforce_col(x, t)
% Apply integer rounding or discrete-level snapping to a column.
    if ischar(t) && strcmp(t,'int')
        x = round(x);
    elseif isnumeric(t)
        [~, k] = min(abs(x(:) - t(:)'), [], 2);
        x = reshape(t(k), size(x));
    end
end

function S = saturation(T)
% Rough binder-saturation estimate, S = binder volume / open pore volume.
% UNVERIFIED illustrative model - replace with your calibrated derivation
% (you already have V_drop = 6.85 pL and phi = 0.48). Used here only to
% check that the DOE spans a useful saturation window, NOT fed to the GP.
    Vdrop = 6.85e-6;                         % mm^3 per drop (6.85 pL)
    phi   = 0.48;                            % powder packing fraction
    mm    = 25.4;                            % in -> mm
    % X pitch scales with dpi; Y pitch fixed by 300 dpi hardware nozzle pitch
    drops_per_mm2 = (T.density/100) .* T.layer_passes .* (T.dpi/mm) .* (300/mm);
    Vbinder = drops_per_mm2 * Vdrop;                 % mm^3/mm^2 = depth (mm)
    Vpore   = (T.layer_thickness*1e-3) .* (1 - phi); % um -> mm pore depth
    S = Vbinder ./ Vpore;
end

function Y = demo_response(X)
% Plausible-looking synthetic response so the pipeline runs before real
% data exists. Peak near mid-saturation, penalize extremes. NOT physical.
    Xn = (X - min(X)) ./ (max(X) - min(X) + eps);
    Y = 0.90 ...
        - 2.5*(Xn(:,1) - 0.55).^2 ...        % density sweet spot
        - 0.8*(Xn(:,5) - 0.40).^2 ...        % layer-thickness effect
        + 0.30*Xn(:,2) ...                   % higher dpi -> denser
        - 0.20*Xn(:,4) ...                   % faster speed -> less imbibition
        + 0.03*randn(size(X,1),1);           % measurement noise
end
