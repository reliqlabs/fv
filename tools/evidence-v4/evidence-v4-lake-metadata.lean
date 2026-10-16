module

prelude
public import Init.System.IO
import Lake
import Lake.Load.Package
import Lake.Load.Toml
import all Lake.Load.Lean.Elab
import Lake.Load.Lean.Eval

open Lean System Lake

private def readPackage (cfg : LoadConfig) : LogIO (Package × NameMap String) := do
  Lean.searchPathRef.set cfg.lakeEnv.leanSearchPath
  let ⟨cfg, h⟩ ← resolveConfigFile "[metadata]" cfg
  let options ← if cfg.configLang?.get h == .lean && !cfg.reconfigure then do
    let some filename := cfg.configFile.fileName
      | error "Invalid Lake configuration filename"
    let trace := cfg.configDir / (FilePath.mk filename).withExtension "olean.trace"
    if (← trace.pathExists) then
      let bytes ← IO.FS.readFile trace
      match Json.parse bytes >>= (·.getObjValAs? (NameMap String) "options") with
      | .ok options => pure options
      | .error message => error s!"Invalid Lake cached configuration: {message}"
    else pure cfg.lakeOpts
  else pure cfg.lakeOpts
  let cfg := {cfg with lakeOpts := options}
  let fileCfg ← match cfg.configLang?.get h with
    | .toml => loadTomlConfig cfg
    | .lean => do
      let env ← elabConfigFile cfg.pkgIdx cfg.pkgName cfg.pkgDir cfg.lakeOpts cfg.leanOpts cfg.configFile
      LakefileConfig.loadFromEnv env cfg.leanOpts
  return (mkPackage cfg fileCfg, options)

private def packageJSON (pkg : Package) (env : Lake.Env) (cfg : LoadConfig) (options : NameMap String) : Json := Json.mkObj [
  ("name", toJson pkg.prettyName),
  ("directory", toJson pkg.dir.toString),
  ("sourceDirectories", toJson (#[pkg.srcDir.toString] ++ pkg.targetDecls.filterMap fun decl =>
    if let some config := decl.toConfigDecl.leanLibConfig? then
      some (pkg.srcDir / config.srcDir.normalize).toString
    else if let some config := decl.toConfigDecl.leanExeConfig? then
      some (pkg.srcDir / config.srcDir.normalize).toString
    else none)),
  ("inputPaths", toJson (pkg.targetDecls.filterMap fun decl =>
    if let some config := decl.toConfigDecl.config? InputFile.configKind then
      some (pkg.dir / config.path).toString
    else if let some config := decl.toConfigDecl.config? InputDir.configKind then
      some (pkg.dir / config.path).toString
    else none)),
  ("configuration", toJson pkg.configFile.toString),
  ("configurationOptions", toJson options),
  ("configurationCacheDirectory", toJson cfg.configDir.toString),
  ("manifest", toJson pkg.manifestFile.toString),
  ("lakeDirectory", toJson pkg.lakeDir.toString),
  ("packagesDirectory", toJson pkg.pkgsDir.toString),
  ("buildDirectory", toJson pkg.buildDir.toString),
  ("leanLibraryDirectory", toJson pkg.leanLibDir.toString),
  ("nativeLibraryDirectory", toJson pkg.sharedLibDir.toString),
  ("binaryDirectory", toJson pkg.binDir.toString),
  ("irDirectory", toJson pkg.irDir.toString),
  ("cacheDirectory", toJson (computeLakeCache pkg env).dir.toString),
  ("dependencies", toJson (pkg.depConfigs.map fun dep => dep.name.toString)),
  ("dependencyOptions", Json.arr (pkg.depConfigs.map fun dep => Json.mkObj [
    ("name", toJson dep.name.toString), ("options", toJson dep.opts)])),
  ("artifactCache", toJson (pkg.enableArtifactCache? <|> env.enableArtifactCache?)),
  ("restoreArtifacts", toJson (pkg.restoreAllArtifacts? <|> env.restoreAllArtifacts?)),
  ("systemConfiguration", toJson (env.lakeConfig?.map (·.toString))),
  ("leanExecutable", toJson env.lean.lean.toString),
  ("lakeExecutable", toJson env.lake.lake.toString),
  ("compiler", toJson env.lean.cc.toString),
  ("archiver", toJson env.lean.ar.toString),
  ("nativeArguments", toJson (pkg.config.weakLeancArgs ++ pkg.config.moreLeancArgs ++ pkg.config.weakLinkArgs ++ pkg.config.moreLinkArgs)),
  ("leanArguments", toJson (pkg.config.weakLeanArgs ++ pkg.config.moreLeanArgs)),
  ("unresolvedNativeTargets", toJson (!pkg.config.moreLinkObjs.isEmpty || !pkg.config.moreLinkLibs.isEmpty || pkg.targetDecls.any fun decl =>
    if let some config := decl.toConfigDecl.leanLibConfig? then
      !config.moreLinkObjs.isEmpty || !config.moreLinkLibs.isEmpty
    else if let some config := decl.toConfigDecl.leanExeConfig? then
      !config.moreLinkObjs.isEmpty || !config.moreLinkLibs.isEmpty
    else decl.kind.isAnonymous || decl.kind == ExternLib.configKind)),
  ("targetArguments", Json.arr (pkg.targetDecls.filterMap fun decl =>
    if let some config := decl.toConfigDecl.leanLibConfig? then
      some (Json.mkObj [("native", toJson (config.weakLeancArgs ++ config.moreLeancArgs ++ config.weakLinkArgs ++ config.moreLinkArgs)), ("lean", toJson (config.weakLeanArgs ++ config.moreLeanArgs))])
    else if let some config := decl.toConfigDecl.leanExeConfig? then
      some (Json.mkObj [("native", toJson (config.weakLeancArgs ++ config.moreLeancArgs ++ config.weakLinkArgs ++ config.moreLinkArgs)), ("lean", toJson (config.weakLeanArgs ++ config.moreLeanArgs))])
    else none)),
  ("initialLeanPath", toJson (env.initLeanPath.map (·.toString)).toArray),
  ("initialSourcePath", toJson (env.initLeanSrcPath.map (·.toString)).toArray)
]

public def main (args : List String) : IO UInt32 := do
  let [sysroot, workspace, directory, configuration, manifest, packageNameJSON, packageIndex, optionsJSON, reconfigure, elanPresent] := args
    | throw <| IO.userError "Invalid Lake metadata arguments"
  let some idx := packageIndex.toNat?
    | throw <| IO.userError "Invalid Lake package index"
  let packageName : String ← match Json.parse packageNameJSON >>= fromJson? with
    | .ok name => pure name
    | .error message => throw <| IO.userError message
  let options : NameMap String ← match Json.parse optionsJSON >>= fromJson? with
    | .ok opts => pure opts
    | .error message => throw <| IO.userError message
  let lean ← LeanInstall.get sysroot (collocated := true)
  let elan? ← if elanPresent == "true" then findElanInstall? else pure none
  let lakeEnv ← (Lake.Env.compute (LakeInstall.ofLean lean) lean elan?).toIO IO.userError
  let cfg : LoadConfig := {
    lakeEnv, wsDir := workspace, pkgDir := directory,
    relConfigFile := configuration, configFile := FilePath.mk directory / configuration,
    relManifestFile := manifest, pkgName := (if packageName.isEmpty then .anonymous else packageName.toName), pkgIdx := idx, lakeOpts := options,
    reconfigure := reconfigure == "true", updateDeps := false, updateToolchain := false
  }
  let some (pkg, effectiveOptions) ← (readPackage cfg).toBaseIO {out := .stderr, ansiMode := .noAnsi}
    | throw <| IO.userError "Lake package metadata failed"
  IO.println (packageJSON pkg lakeEnv cfg effectiveOptions).compress
  return 0
