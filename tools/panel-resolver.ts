import * as path from "node:path";
import type {
	CustomToolFactory,
	PanelRole,
	ResolvedPanelMember,
} from "@oh-my-pi/pi-coding-agent";

interface RegistryVoice {
	id: string;
	omp_model?: string;
	omp_calibration?: string;
}

interface ResolvedSeat {
	seat_id: string;
	declared_family: string;
	requested_selector: string;
	resolved_provider: string;
	resolved_model: string;
	thinking_level: string;
	calibration: string;
	resolved_family: string;
}

const factory: CustomToolFactory = pi => ({
	name: "fv_panel_resolve",
	label: "Resolve FV panel roster",
	description: "Resolve an OMP-defined panel role for the FV execution protocol.",
	parameters: pi.zod.object({
		role: pi.zod.string(),
		mode: pi.zod.enum(["project-plan", "milestone-review"]),
		synthesizer: pi.zod.string().optional(),
		seat_timeout_seconds: pi.zod.number().optional(),
	}),

	async execute(_toolCallId, params, _onUpdate, ctx) {
		const parseSettings = pi.pi?.parsePanelSettings;
		const resolveRole = pi.pi?.resolvePanelRole;
		const resolveLineup = pi.pi?.resolvePanelLineup;
		if (typeof parseSettings !== "function" || typeof resolveRole !== "function" || typeof resolveLineup !== "function") {
			throw new Error(
				"this OMP build does not expose its panel configuration and lineup resolver; " +
					"`omp --agent-bridge-contract` must report panelLineupFreeze",
			);
		}
		if (!ctx.settings) throw new Error("OMP session settings are unavailable");

		const panelSettings = parseSettings(ctx.settings.get("panel"));
		const role = resolveRole(panelSettings, params.role);
		const context = { modelRegistry: ctx.modelRegistry, settings: ctx.settings };
		const lineup = resolveLineup({
			context,
			roleId: role.roleId,
			role: role.role,
			taskMode: params.mode === "project-plan" ? "plan" : "answer",
		});
		const synthesizerRole: PanelRole = {
			strategy: "independent",
			members: [{ model: params.synthesizer ?? "@plan" }],
		};
		const synthesizer = resolveLineup({
			context,
			roleId: `${role.roleId}.synthesizer`,
			role: synthesizerRole,
			taskMode: params.mode === "project-plan" ? "plan" : "answer",
		});

		const packageRoot = path.resolve(import.meta.dir, "..");
		const registry = (await Bun.file(path.join(packageRoot, "registry", "voices.json")).json()) as {
			voices?: RegistryVoice[];
		};
		const voices = registry.voices ?? [];
		const voiceFor = (member: ResolvedPanelMember): RegistryVoice | undefined =>
			voices.find(voice => voice.omp_model === member.model);
		const toSeat = (
			member: ResolvedPanelMember,
			index: number,
			voice: RegistryVoice | undefined,
			seatId?: string,
		): ResolvedSeat => {
			const [provider] = member.selector.split("/");
			if (!provider) throw new Error(`resolved an unqualified selector "${member.selector}"`);
			return {
				seat_id: seatId ?? voice?.id ?? `seat-${index + 1}`,
				// FV's declared-family quorum now comes from OMP's resolved identity,
				// so a human label cannot disagree with the mechanical family gate.
				declared_family: member.family,
				requested_selector: member.requestedSelector,
				resolved_provider: provider,
				resolved_model: member.selector,
				resolved_family: member.family,
				thinking_level: member.thinking ?? "",
				calibration: voice?.omp_calibration ?? "pending",
			};
		};
		const synthMember = synthesizer.members[0];
		if (!synthMember) throw new Error("OMP did not resolve a synthesizer model");
		const seatTimeoutSeconds = params.seat_timeout_seconds ?? 1800;
		if (!Number.isFinite(seatTimeoutSeconds) || seatTimeoutSeconds <= 0) {
			throw new Error("seat_timeout_seconds must be positive");
		}

		const roster = {
			role: role.roleId,
			mode: params.mode,
			min_families: role.role.minFamilies ?? 2,
			seat_timeout_seconds: seatTimeoutSeconds,
			lineup_hash: lineup.lineupHash,
			seats: lineup.members.map((member, index) => toSeat(member, index, voiceFor(member))),
			synthesizer: toSeat(synthMember, 0, voiceFor(synthMember), "synthesizer"),
		};
		return {
			content: [{ type: "text", text: JSON.stringify(roster) }],
			details: roster,
		};
	},
});

export default factory;
