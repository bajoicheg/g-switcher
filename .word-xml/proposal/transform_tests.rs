use super::*;

fn package(runs: &str) -> String {
    format!("<pkg:package xmlns:pkg=\"http://schemas.microsoft.com/office/2006/xmlPackage\"><pkg:part pkg:name=\"/word/document.xml\" pkg:contentType=\"application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml\"><pkg:xmlData><w:document xmlns:w=\"http://schemas.openxmlformats.org/wordprocessingml/2006/main\"><w:body><w:p>{runs}</w:p></w:body></w:document></pkg:xmlData></pkg:part></pkg:package>")
}
fn evidence(text: &str) -> (FreshBinding, EffectiveDependencyEvidence) {
    let binding = FreshBinding { operation: 7, word_pid: 42, word_birth: 99,
        document: [1; 32], range_start: 10, range_end: 10 + text.encode_utf16().count() as u32,
        input_epoch: 4, policy_epoch: 3 };
    let proof = EffectiveDependencyEvidence { binding: binding.clone(), source_xml:String::new(), source_context: [2;32],
        destination_context: [2;32], effective_per_utf16: (0..text.encode_utf16().count()).map(|i|if i<3{[3;32]}else{[4;32]}).collect(),
        dependencies: DependencyAssessment::NoImplicitOrImportedDependencies };
    (binding, proof)
}
fn make(xml: &str, original: &str, replacement: &str) -> Result<XmlPlan, Refusal> {
    let (binding, mut proof) = evidence(original);
    proof.source_xml=xml.to_owned();
    prepare(xml, original, replacement, &binding, Some(&proof))
}
#[test]
fn mixed_run_mapping_changes_only_text_bytes() {
    let xml = package("<w:r><w:rPr><w:b/><w:color w:val=\"FF0000\"/></w:rPr><w:t>ghb</w:t></w:r><w:r><w:rPr><w:i/><w:sz w:val=\"28\"/></w:rPr><w:t>dtn</w:t></w:r>");
    let plan = make(&xml,"ghbdtn","привет").unwrap();
    assert_eq!(plan.xml(), xml.replace(">ghb<",">при<").replace(">dtn<",">вет<"));
    assert_eq!(plan.mapping().iter().map(|m| m.utf16_len).collect::<Vec<_>>(), vec![3,3]);
    assert_eq!(plan.effective_per_utf16(), &[[3;32],[3;32],[3;32],[4;32],[4;32],[4;32]]);
    assert_eq!(plan.original(),"ghbdtn");assert_eq!(plan.replacement(),"привет");assert_eq!(plan.binding().operation,7);
}
#[test]
fn entity_decoding_maps_characters_and_escapes_replacement() {
    let xml=package("<w:r><w:t>&#x61;&#98;c</w:t></w:r>");
    assert_eq!(make(&xml,"abc","язь").unwrap().xml(), xml.replace("&#x61;&#98;c","язь"));
    assert_eq!(escape_text("я&<>"),"я&amp;&lt;&gt;");
}
#[test]
fn predefined_and_numeric_entities_have_exact_decoded_mapping() {
    assert_eq!(decode("&lt;&amp;&gt;&quot;&apos;").unwrap(),"<&>\"'");
    assert!(make(&package("<w:r><w:t>&amp;bc</w:t></w:r>"),"&bc","abc").is_err());
}
#[test]
fn unchanged_nodes_preserve_original_entity_and_namespace_bytes() {
    let xml=package("<w:r><w:t>a&#98;</w:t></w:r><w:r><w:t>cd</w:t></w:r>");
    assert_eq!(make(&xml,"abcd","abде").unwrap().xml(),xml.replace(">cd<",">де<"));
}
#[test]
fn exact_original_mismatch_refuses_before_planning() {
    assert_eq!(make(&package("<w:r><w:t>abc</w:t></w:r>"),"abd","xyz"),Err(Refusal::OriginalMismatch));
}
#[test]
fn missing_or_stale_effective_dependency_evidence_refuses() {
    let xml=package("<w:r><w:t>abc</w:t></w:r>");let (binding,mut proof)=evidence("abc");proof.source_xml=xml.clone();
    assert_eq!(prepare(&xml,"abc","xyz",&binding,None),Err(Refusal::EvidenceRequired));
    proof.binding.input_epoch+=1;
    assert_eq!(prepare(&xml,"abc","xyz",&binding,Some(&proof)),Err(Refusal::EvidenceMismatch));
    proof.binding=binding.clone();proof.source_xml=xml.replace("abc","abd");
    assert_eq!(prepare(&xml,"abc","xyz",&binding,Some(&proof)),Err(Refusal::EvidenceMismatch));
    proof.source_xml=xml.clone();proof.destination_context=[9;32];
    assert_eq!(prepare(&xml,"abc","xyz",&binding,Some(&proof)),Err(Refusal::EvidenceMismatch));
}
#[test]
fn inherited_or_unmeasured_formatting_and_imported_dependencies_refuse() {
    let xml=package("<w:r><w:t>abc</w:t></w:r>");let (binding,mut proof)=evidence("abc");proof.source_xml=xml.clone();
    proof.dependencies=DependencyAssessment::Unknown;
    assert_eq!(prepare(&xml,"abc","xyz",&binding,Some(&proof)),Err(Refusal::DependencyUnproven));
    proof.dependencies=DependencyAssessment::NoImplicitOrImportedDependencies;
    proof.effective_per_utf16[0]=[0;32];
    assert_eq!(prepare(&xml,"abc","xyz",&binding,Some(&proof)),Err(Refusal::EvidenceMismatch));
}
#[test]
fn unsupported_word_structures_never_get_a_plan() {
    for node in ["<w:tab/>","<w:br/>","<w:fldChar/>","<w:instrText>x</w:instrText>","<w:bookmarkStart/>","<w:ins/>","<w:del/>","<w:drawing/>","<w:sdt/>","<w:hyperlink/>","<w:commentRangeStart/>","<w:sectPr/>"] {
        assert!(make(&package(&format!("<w:r><w:t>abc</w:t>{node}</w:r>")),"abc","xyz").is_err(),"{node}");
    }
    assert!(make(&package("<w:pPr><w:pStyle w:val=\"Normal\"/></w:pPr><w:r><w:t>abc</w:t></w:r>"),"abc","xyz").is_err());
}
#[test]
fn style_theme_relationship_and_unknown_attribute_refuse() {
    for props in ["<w:rStyle w:val=\"Strong\"/>","<w:rFonts w:asciiTheme=\"minorHAnsi\"/>","<w:color w:themeColor=\"accent1\"/>","<w:unknown/>"] {
        assert!(make(&package(&format!("<w:r><w:rPr>{props}</w:rPr><w:t>abc</w:t></w:r>")),"abc","xyz").is_err());
    }
    let xml=package("<w:r odd=\"1\"><w:t>abc</w:t></w:r>");assert!(make(&xml,"abc","xyz").is_err());
    let xml=package("<w:r><w:t>abc</w:t></w:r>").replace("</pkg:package>","<pkg:part pkg:name=\"/word/styles.xml\"/></pkg:package>");assert!(make(&xml,"abc","xyz").is_err());
}
#[test]
fn lengths_surrogates_whitespace_delimiters_and_controls_refuse() {
    let xml=package("<w:r><w:t>abc</w:t></w:r>");
    for replacement in ["ab","abcd","ab😀","ab\r","ab\n","ab\t","ab ","ab\0","ab\u{7f}","ab,","ab.","ab1","ab-","ab\u{301}","ab\u{345}","ab日"] {assert!(make(&xml,"abc",replacement).is_err());}
    assert!(make(&package("<w:r><w:t>ab😀</w:t></w:r>"),"ab😀","abcd").is_err());
    assert!(make(&package("<w:r><w:t>abc def</w:t></w:r>"),"abc def","xyz uvw").is_err());
    assert!(make(&xml,"abc","abc").is_err());
    assert!(make(&package("<w:r><w:t>abc,</w:t></w:r>"),"abc,","xyz,").is_err());
}
#[test]
fn dtd_entity_cdata_comment_pi_and_malformed_xml_refuse() {
    for prefix in ["<!DOCTYPE x [<!ENTITY boom SYSTEM 'file:///tmp/x'>]>","<!--comment-->","<?xml version='1.0'?>"] {assert!(make(&(prefix.to_owned()+&package("<w:r><w:t>abc</w:t></w:r>")),"abc","xyz").is_err());}
    for text in ["<![CDATA[abc]]>","&boom;","&#0;","&#xD800;","&#99999999999999999999;","abc<", "a&b", "ab\u{85}"] {assert!(make(&package(&format!("<w:r><w:t>{text}</w:t></w:r>")),"abc","xyz").is_err());}
    assert!(make(&package("<w:r><w:t>abc</w:r></w:t>"),"abc","xyz").is_err());
    assert!(make(&package("\u{85}<w:r><w:t>abc</w:t></w:r>"),"abc","xyz").is_err());
}
#[test]
fn explicit_bounds_reject_excess_xml_runs_text_and_attribute_lengths() {
    assert!(make(&package(&format!("<w:r><w:rPr><w:rFonts w:ascii=\"{}\"/></w:rPr><w:t>abc</w:t></w:r>","A".repeat(MAX_ATTRIBUTE_BYTES+1))),"abc","xyz").is_err());
    assert!(make(&"x".repeat(MAX_XML_BYTES+1),"abc","xyz").is_err());
    let runs="<w:r><w:t>a</w:t></w:r>".repeat(MAX_RUNS+1);
    assert!(make(&package(&runs),&"a".repeat(MAX_RUNS+1),&"b".repeat(MAX_RUNS+1)).is_err());
    assert!(make(&package(&format!("<w:r><w:t>{}</w:t></w:r>","a".repeat(MAX_TEXT_UNITS+1))),&"a".repeat(MAX_TEXT_UNITS+1),&"b".repeat(MAX_TEXT_UNITS+1)).is_err());
}
#[test]
fn direct_run_properties_are_byte_preserved_without_effective_claim() {
    let properties="<w:rFonts w:ascii=\"Arial\" w:hAnsi=\"Arial\"/><w:b w:val=\"0\"/><w:i/><w:u w:val=\"single\"/><w:sz w:val=\"24\"/><w:szCs w:val=\"24\"/><w:color w:val=\"ABCDEF\"/><w:highlight w:val=\"yellow\"/><w:lang w:val=\"ru-RU\" w:eastAsia=\"ja-JP\"/>";
    let xml=package(&format!("<w:r><w:rPr>{properties}</w:rPr><w:t xml:space=\"preserve\">abc</w:t></w:r>"));
    let plan=make(&xml,"abc","xyz").unwrap();assert!(plan.xml().contains(properties));assert!(plan.xml().contains("xml:space=\"preserve\""));
}

#[test]
fn debug_output_contains_no_source_or_replacement_text() {
 let xml=package("<w:r><w:t>secret</w:t></w:r>");let plan=make(&xml,"secret","hidden").unwrap();
 let formatted=format!("{plan:?}");assert!(!formatted.contains("secret"));assert!(!formatted.contains("hidden"));assert!(!formatted.contains("w:t"));
 let (_,proof)=evidence("secret");assert!(!format!("{proof:?}").contains("secret"));
}
#[test]
fn pinned_synthetic_flatopc_fixture_maps_runs_but_styles_fixture_refuses() {
 let xml=include_str!("fixtures/synthetic-mixed-flatopc.xml");
 let plan=make(xml,"ghbdtn","привет").unwrap();
 assert_eq!(plan.xml(),xml.replace(">ghb<",">при<").replace(">dtn<",">вет<"));
 assert!(make(include_str!("fixtures/synthetic-styles-flatopc.xml"),"ghbdtn","привет").is_err());
}
