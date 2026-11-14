export const tissueImages = {
	wholeSlide:
		'https://images.unsplash.com/photo-1716833322987-bfef9f913822?crop=entropy&cs=tinysrgb&fit=max&fm=jpg&ixlib=rb-4.1.0&q=88&w=1600',
	epithelium:
		'https://images.unsplash.com/photo-1716833323041-eb8dd5c54aba?crop=entropy&cs=tinysrgb&fit=max&fm=jpg&ixlib=rb-4.1.0&q=88&w=900',
	stomach:
		'https://images.unsplash.com/photo-1647083701139-3930542304cf?crop=entropy&cs=tinysrgb&fit=max&fm=jpg&ixlib=rb-4.1.0&q=88&w=900',
	nci: 'https://images.unsplash.com/photo-1631048008444-cd48b97b5564?crop=entropy&cs=tinysrgb&fit=max&fm=jpg&ixlib=rb-4.1.0&q=88&w=900'
};

export const cases = [
	{
		id: 'skin-014218',
		specialty: 'Dermatopathology',
		ageSex: '67 · F',
		status: 'Open',
		pathologist: 'Dr A. Okafor',
		slides: 2,
		icd10: '—',
		conclusion: 'Awaiting report',
		accessioned: 'Today, 09:42',
		image: tissueImages.wholeSlide
	},
	{
		id: 'breast-008412',
		specialty: 'Breast',
		ageSex: '54 · F',
		status: 'Open',
		pathologist: 'Dr A. Okafor',
		slides: 1,
		icd10: '—',
		conclusion: 'Awaiting report',
		accessioned: 'Today, 08:16',
		image: tissueImages.epithelium
	},
	{
		id: 'thorax-002917',
		specialty: 'Thoracic',
		ageSex: '72 · M',
		status: 'Open',
		pathologist: 'Dr A. Okafor',
		slides: 3,
		icd10: '—',
		conclusion: 'Awaiting report',
		accessioned: 'Yesterday, 16:34',
		image: tissueImages.stomach
	},
	{
		id: 'skin-011904',
		specialty: 'Dermatopathology',
		ageSex: '61 · M',
		status: 'Signed out',
		pathologist: 'Dr M. Laurent',
		slides: 1,
		icd10: 'C44.5',
		conclusion: 'Invasive squamous proliferation with keratinisation.',
		accessioned: '12 Nov, 14:03',
		image: tissueImages.nci
	},
	{
		id: 'skin-009671',
		specialty: 'Dermatopathology',
		ageSex: '58 · F',
		status: 'Signed out',
		pathologist: 'Dr E. Mensah',
		slides: 2,
		icd10: 'D03.6',
		conclusion: 'Atypical melanocytic proliferation, completely excised.',
		accessioned: '11 Nov, 10:21',
		image: tissueImages.wholeSlide
	},
	{
		id: 'colorectal-004502',
		specialty: 'Gastrointestinal',
		ageSex: '70 · M',
		status: 'Signed out',
		pathologist: 'Dr S. Chen',
		slides: 2,
		icd10: 'C18.7',
		conclusion: 'Moderately differentiated gland-forming neoplasm.',
		accessioned: '10 Nov, 15:49',
		image: tissueImages.stomach
	}
];

export const evidenceResults = [
	{
		...cases[3],
		score: 0.94,
		matchedBy: ['Morphology', 'Report'],
		patchCount: 14,
		passage:
			'Irregular nests of atypical squamous cells with prominent keratinisation and surrounding stromal response.'
	},
	{
		...cases[4],
		score: 0.87,
		matchedBy: ['Morphology'],
		patchCount: 9,
		passage:
			'An asymmetrical junctional proliferation is present with focal pagetoid spread and dermal inflammation.'
	},
	{
		...cases[5],
		score: 0.79,
		matchedBy: ['Semantic'],
		patchCount: 6,
		passage:
			'Infiltrative glandular structures are accompanied by desmoplastic stroma and focal necrosis.'
	}
];

export const annotations = [
	{
		label: 'Keratinising focus',
		note: 'Central whorl with abrupt eosinophilic maturation.',
		author: 'You',
		time: '4 min ago',
		kind: 'Rectangle'
	},
	{
		label: 'Inflammatory edge',
		note: 'Dense interface infiltrate at the lower border.',
		author: 'Dr M. Laurent',
		time: 'Yesterday',
		kind: 'Point'
	}
];

export const jobs = [
	{
		dataset: 'HISTAI-skin-b1',
		path: 'case_014218/slide_HE_1.tiff',
		status: 'Running',
		stage: 'Projecting features',
		time: '2 min ago'
	},
	{
		dataset: 'HISTAI-breast',
		path: 'case_008412/slide_HE_1.tiff',
		status: 'Done',
		stage: 'Indexed',
		time: '18 min ago'
	},
	{
		dataset: 'HISTAI-thorax',
		path: 'case_002917/slide_HE_2.tiff',
		status: 'Failed',
		stage: 'Segmenting tissue',
		time: 'Yesterday'
	}
];
